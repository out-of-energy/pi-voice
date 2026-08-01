-- ============================================================
--  Whisper 语音输入法 (Voice Input Method)
--  热键: ⌃⌥Space
--  录音: ffmpeg (avfoundation) + silencedetect 自动停止
--  转写: Whisper 常驻守护进程 (whisper_daemon.py, 模型常驻内存)
--        守护进程不可用时自动回退 CLI (mlx_whisper)
--  调试日志: /tmp/pi-voice-debug.log
--  守护日志: /tmp/pi-whisper-daemon.log
-- ============================================================

local FFMPEG = "/opt/homebrew/bin/ffmpeg"
local OUT = "/tmp/pi-voice-input.wav"
local FFLOG = "/tmp/pi-voice-ff.log"
local LOG = "/tmp/pi-voice-debug.log"

-- 转写语言: "auto" 自动检测 / "zh" 强制中文(中英混说推荐)
local LANG = "auto"
local WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"

-- 常驻守护进程
local DAEMON_URL = "http://127.0.0.1:18765"
local DAEMON_SCRIPT = os.getenv("HOME") .. "/.hammerspoon/whisper_daemon.py"

local recording = false
local transcribing = false
local cancelled = false
local recTask = nil
local monTimer = nil
local daemonPython = nil

local function log(msg)
  local f = io.open(LOG, "a")
  if f then
    f:write(os.date("%Y-%m-%d %H:%M:%S") .. "  " .. tostring(msg) .. "\n")
    f:close()
  end
end

-- ---------- 静音检测: 返回 (silence_start, silence_end) ----------
local function parseSilence()
  local s, e = nil, nil
  local f = io.open(FFLOG, "r")
  if f then
    for line in f:lines() do
      local st = line:match("silence_start: ([%d%.]+)")
      local en = line:match("silence_end: ([%d%.]+)")
      if st then s = st end
      if en then e = en end
    end
    f:close()
  end
  return s, e
end

-- ---------- 说完自动停止 ----------
local function checkSilence()
  if not recording then return end
  local s, e = parseSilence()
  if not s then return end
  local lastIsSilence = true
  if e and tonumber(e) > tonumber(s) then lastIsSilence = false end
  if lastIsSilence and tonumber(s) > 1.5 then
    log("auto-stop: silence_start=" .. s)
    if recTask then recTask:terminate() end
  end
end

-- ==================== 守护进程管理 ====================

local function fileExists(p)
  local f = io.open(p, "rb")
  if f then f:close() return true end
  return false
end

local function firstLine(p)
  local f = io.open(p, "r")
  if not f then return "" end
  local l = f:read("*l") or ""
  f:close()
  return l
end

-- 找到 mlx_whisper 的 Python 解释器 (直接探测 pipx 路径 + CLI shebang)
local function findDaemonPython()
  if daemonPython then return daemonPython end
  local home = os.getenv("HOME") or ""
  if home == "" then
    home = hs.execute("echo $HOME"):gsub("%s+$", "")
  end
  -- 注意: 不能用 {nil, a, b} 字面量建表 —— ipairs 遇到首个 nil 会直接停止
  local candidates = {}
  local function add(p)
    if p and p ~= "" then table.insert(candidates, p) end
  end
  add(os.getenv("PI_WHISPER_PY"))
  add(home .. "/.local/pipx/venvs/mlx-whisper/bin/python")
  add(home .. "/.local/bin/mlx_whisper")
  for _, c in ipairs(candidates) do
    if fileExists(c) then
      if c:match("mlx_whisper$") then
        local shebang = firstLine(c)
        if shebang:match("^#!") then c = shebang:sub(3):gsub("%s+$", "") end
      end
      daemonPython = c
      log("daemon python: " .. c)
      return c
    end
  end
  log("mlx_whisper python 未找到，仅使用 CLI 回退路径")
  return nil
end

local function daemonAlive()
  local r = hs.execute("curl -s --max-time 2 " .. DAEMON_URL .. "/health")
  return r:find("ok", 1, true) ~= nil
end

local function spawnDaemon()
  local py = findDaemonPython()
  if not py then return false end
  if not fileExists(DAEMON_SCRIPT) then
    log("守护脚本不存在: " .. DAEMON_SCRIPT)
    return false
  end
  local cmd = '/usr/bin/nohup "' .. py .. '" "' .. DAEMON_SCRIPT .. '" >/dev/null 2>&1 &'
  hs.task.new("/bin/bash", function() end, { "-c", cmd }):start()
  log("守护进程拉起: " .. cmd)
  return true
end

-- 同步等待守护进程就绪 (阻塞, 最多 maxSec 秒)
local function ensureDaemonSync(maxSec)
  if daemonAlive() then return true end
  if not spawnDaemon() then return false end
  local waited = 0
  while waited < maxSec do
    hs.timer.usleep(400000)
    waited = waited + 0.4
    if daemonAlive() then return true end
  end
  return false
end

-- ==================== 转写结果处理 (两个路径共用) ====================

local function finishTranscribe(text, ok)
  transcribing = false
  if ok and #text > 0 then
    hs.eventtap.keyStrokes(text)
    hs.alert.show("✅ 已输入")
    log("typed: " .. text)
  else
    hs.alert.show("⚠️ 没听清，请再试一次")
    log("no text result" .. (ok and "" or (" daemon_err=" .. tostring(text))))
  end
  os.remove(OUT)
  os.remove(FFLOG)
  log("cleaned temp files")
end

-- ---------- 转写路径 1: 常驻守护进程 ----------
local function transcribeViaDaemon()
  local langField = ""
  if LANG ~= "auto" then langField = ',"language":"' .. LANG .. '"' end
  local data = '{"audio":"' .. OUT .. '"' .. langField .. '}'
  local cmd = "curl -s --max-time 120 -X POST '" .. DAEMON_URL ..
    "/transcribe' -H 'Content-Type: application/json' -d '" .. data .. "'"
  local t = hs.task.new("/bin/bash", function(exit, stdout, stderr)
    local out = (stdout or ""):gsub("^%s+", ""):gsub("%s+$", "")
    local obj = hs.json.decode(out)
    if obj and obj.text then
      log("daemon transcribe ok: " .. obj.text)
      finishTranscribe(obj.text, true)
    else
      log("daemon 转写失败, 回退 CLI. exit=" .. exit .. " out=" .. out ..
        " err=" .. (stderr or ""):gsub("%s+$", ""))
      transcribeViaCLI()
    end
  end, { "-c", cmd })
  t:start()
  return true
end

-- ---------- 转写路径 2: CLI 回退 (原实现) ----------
local function transcribeViaCLI()
  local langArg = ""
  if LANG ~= "auto" then langArg = " --language " .. LANG end
  local cmd = 'export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"; ' ..
    'mlx_whisper "' .. OUT .. '" --model ' .. WHISPER_MODEL .. langArg ..
    ' -f txt --output-dir /tmp --output-name pi_voice >/dev/null 2>/tmp/pi-voice-w.err; ' ..
    'if [ -f /tmp/pi_voice.txt ]; then sed \'s/\\[[0-9:. ]*--> [0-9:. ]*\\] //g\' /tmp/pi_voice.txt; ' ..
    'echo "TTS-OK"; else echo "TTS-FAIL"; fi; ' ..
    'rm -f /tmp/pi_voice.txt /tmp/pi-voice-w.err'
  local t = hs.task.new("/bin/bash", function(exit, stdout, stderr)
    local out = (stdout or ""):gsub("%s+$", "")
    local ok = out:find("TTS-OK", 1, true) ~= nil
    local text = out:gsub("TTS%-OK", ""):gsub("TTS%-FAIL", ""):gsub("^%s+", ""):gsub("%s+$", "")
    finishTranscribe(text, ok)
  end, { "-c", cmd })
  t:start()
  return true
end

-- ---------- 转写入口 ----------
local function transcribe()
  transcribing = true
  hs.alert.show("⏳ 转写中…")
  -- 优先守护进程: 拉起并等待就绪(首次 ~4s), 失败回退 CLI
  if ensureDaemonSync(15) then
    transcribeViaDaemon()
  else
    log("守护进程不可用, 使用 CLI")
    transcribeViaCLI()
  end
end

-- ---------- 停止录音 ----------
local function stopRecording()
  if monTimer then monTimer:stop() monTimer = nil end
  if recTask then recTask:terminate() recTask = nil end
  recording = false
end

local function cancelRecording()
  cancelled = true
  stopRecording()
  os.remove(OUT)
  os.remove(FFLOG)
  hs.alert.show("❌ 已取消")
  log("cancelled")
end

-- ---------- 开始录音 ----------
local function startRecording()
  log("hotkey (recording=" .. tostring(recording) .. ", transcribing=" .. tostring(transcribing) .. ")")
  if transcribing then
    hs.alert.show("⏳ 正在转写，请稍等")
    return
  end
  if recording then
    cancelRecording()
    return
  end

  recording = true
  cancelled = false
  os.remove(OUT)
  os.remove(FFLOG)
  hs.alert.show("🎙 录音中… 说完自动停止")
  log("ffmpeg: start")

  local cmd = '"' .. FFMPEG .. '" -y -loglevel info -f avfoundation -i ":0" -af "silencedetect=noise=-30dB:d=0.8" -t 25 "' .. OUT .. '" 2> "' .. FFLOG .. '"'
  recTask = hs.task.new("/bin/bash", function(exit, stdout, stderr)
    stopRecording()
    log("ffmpeg: exit=" .. exit)
    if cancelled then return end
    local size = 0
    local h = io.open(OUT, "rb")
    if h then size = h:seek("end") h:close() end
    log("ffmpeg: size=" .. size)
    if size > 1000 then
      transcribe()
    else
      hs.alert.show("❌ 没录到声音")
      log("empty recording")
    end
  end, { "-c", cmd })
  recTask:start()

  monTimer = hs.timer.doEvery(0.3, checkSilence)
end

-- ---------- 热键绑定 ----------
hs.hotkey.bind({ "ctrl", "alt" }, "space", startRecording)

-- ---------- 守护进程: 启动时拉起 + 定期保活 ----------
if not daemonAlive() then
  spawnDaemon()
end
hs.timer.doEvery(120, function()
  if not daemonAlive() then
    log("守护进程掉线, 重新拉起")
    spawnDaemon()
  end
end)

hs.alert.show("🎤 Whisper 语音输入法已就绪 — 按 ⌃⌥Space 说话")
log("config loaded")
