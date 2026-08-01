import { execFile, execFileSync, type ChildProcess } from "node:child_process";
import { appendFileSync, existsSync, readdirSync, readFileSync, rmSync, statSync, unlinkSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/**
 * Speak pi's full reply aloud using Microsoft Edge TTS (晓晓 zh-CN-XiaoxiaoNeural).
 * Reads both Chinese and English. Same engine as the OpenClaw TTS server.
 * - Override voice: PI_SPEAK_VOICE (e.g. en-US-AriaNeural)
 * - Disable: PI_SPEAK_OFF=1
 *
 * 朗读控制 (需求3: 打断/跳过):
 *   长回复分段排队朗读; 通过 /tmp/pi-speak.ctl 控制:
 *     "skip <ms>"  → 跳过当前段, 播下一段(跳到下一次要朗读的内容; 跳完即等下一次回复)
 *     "stop <ms>"  → 停止朗读, 清空队列, 直到下一次回复再读
 *   控制端: Hammerspoon 全局热键 (voice-input/init.lua):
 *     ⌃⌥K = 跳到下一段    ⌃⌥I = 停止朗读
 */
export default function (pi: ExtensionAPI) {
  if (process.env.PI_SPEAK_OFF) return;

  const EDGE_TTS = process.env.EDGE_TTS_BIN ?? "edge-tts"; // portable: resolve from PATH (override with EDGE_TTS_BIN=/path/to/edge-tts)
  const VOICE = process.env.PI_SPEAK_VOICE ?? "zh-CN-XiaoxiaoNeural";
  const MAX_CHUNK = Number(process.env.PI_SPEAK_MAX_CHUNK ?? 2000); // edge-tts per-request limit (可用 PI_SPEAK_MAX_CHUNK 调)
  const CTL = "/tmp/pi-speak.ctl";
  const LOG = "/tmp/pi-speak.log";

  // 日志写文件, 不打到 TUI (避免刷屏挡住对话)
  const log = (msg: string) => {
    try {
      appendFileSync(LOG, `${new Date().toISOString()}  ${msg}\n`);
    } catch { /* ignore */ }
  };

  /** Strip Markdown syntax so TTS reads clean, natural text (not symbols). */
  const cleanForTTS = (text: string): string => {
    let t = text;
    // code blocks -> short marker
    t = t.replace(/```[\s\S]*?```/g, " 代码省略。 ");
    // inline code -> keep inner text
    t = t.replace(/`([^`]+)`/g, "$1");
    // images ![alt](url) -> alt text
    t = t.replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1");
    // links [text](url) -> text only
    t = t.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
    // headings # ## ### -> text only
    t = t.replace(/^#{1,6}\s*/gm, "");
    // bold/italic *** ** * ___ __ _
    t = t.replace(/\*\*\*([^*]+)\*\*\*/g, "$1");
    t = t.replace(/\*\*([^*]+)\*\*/g, "$1");
    t = t.replace(/\*([^*]+)\*/g, "$1");
    t = t.replace(/___([^_]+)___/g, "$1");
    t = t.replace(/__([^_]+)__/g, "$1");
    t = t.replace(/(?<![\w])_([^_]+)_(?![\w])/g, "$1");
    // blockquotes >
    t = t.replace(/^\s*>\s?/gm, "");
    // list markers - * + 1. 1) •
    t = t.replace(/^\s*[-*+•]\s+/gm, "");
    t = t.replace(/^\s*\d+[.)]\s+/gm, "");
    // horizontal rules --- *** ___
    t = t.replace(/^\s*(---|\*\*\*|___)\s*$/gm, "");
    // table pipes -> spaces (drop separator rows)
    t = t.replace(/^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/gm, "");
    t = t.replace(/\|/g, " ");
    // emoji & decorative symbols (faces, flags, dingbats, arrows, shapes...)
    t = t.replace(
      /[\u{1F000}-\u{1FAFF}\u{1F1E6}-\u{1F1FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{2190}-\u{21FF}\u{25A0}-\u{25FF}\u{FE0F}\u{200D}\u{20E3}\u{00A9}\u{00AE}\u{2122}]/gu,
      ""
    );
    // remaining underscores -> space (so file_name reads as "file name", not "underscore")
    t = t.replace(/_/g, " ");
    // speaker name -> first person (voice should not refer to itself as 晓晓/Xiaoxiao)
    t = t.replace(/Xiaoxiao's/gi, "My");
    t = t.replace(/Xiaoxiao/gi, "I");
    t = t.replace(/晓晓/g, "我");
    // collapse whitespace
    t = t.replace(/[ \t]+/g, " ");
    t = t.replace(/\n{3,}/g, "\n\n");
    return t.trim();
  };

  // ---------------- 可中断的队列播放 ----------------

  // 启动即忽略旧的 ctl 指令(防止上次会话的 stop/skip 残留把新回复静音)
  let lastCtlStamp = Date.now();
  // 清理残留: 孤儿 mp3 + 上次扩展实例遗留的 afplay/edge-tts
  // (reload 后旧实例的子进程会变孤儿, 不杀的话 skip/stop 控制不到它们)
  try {
    execFileSync("pkill", ["-9", "-f", "pi-speak-"]);
  } catch { /* 没有残留进程 */ }
  try {
    for (const f of readdirSync("/tmp")) {
      if (f.startsWith("pi-speak-") && f.endsWith(".mp3")) {
        try { rmSync("/tmp/" + f); } catch { /* ignore */ }
      }
    }
  } catch { /* ignore */ }

  let queue: string[] = [];              // 待朗读的段落
  let currentChild: ChildProcess | null = null; // 正在跑的 edge-tts / afplay
  let cancelled = false;                 // 本次(代)朗读是否被取消
  let playing = false;                   // 播放循环是否在运行

  const killCurrent = () => {
    if (currentChild) {
      try { currentChild.kill("SIGKILL"); } catch { /* already dead */ }
      currentChild = null;
    }
  };

  // 兜底: 杀所有引用 pi-speak- 临时文件的进程(afplay/edge-tts)
  // 覆盖两种漏网: 1) 上次扩展实例 reload 后遗留的孤儿; 2) 偶发未被追踪的子进程
  const killAllAudio = () => {
    killCurrent();
    try { execFileSync("pkill", ["-9", "-f", "pi-speak-"]); } catch { /* none */ }
  };

  /** 生成一段 mp3 (edge-tts); 被杀/出错则返回 null */
  const genChunk = (text: string, tmp: string) =>
    new Promise<string | null>((resolve) => {
      const p = execFile(
        EDGE_TTS,
        ["--voice", VOICE, "--text", text, "--write-media", tmp, "--write-subtitles", "/dev/null"],
        { timeout: 120000 },
        (err) => {
          // 被我们主动 kill(SIGKILL) 是 skip/stop 的正常行为, 不打错误日志
          if (err && !(err.signal === "SIGKILL")) {
            log("edge-tts 失败: " + err.message);
          }
          if (err) resolve(null);
        }
      );
      currentChild = p;
      p.once("close", () => resolve(tmp));
    });

  /** 播放一段 mp3 (afplay); 被杀/出错则返回 */
  const playChunk = (tmp: string) =>
    new Promise<void>((resolve) => {
      const p = execFile("/usr/bin/afplay", [tmp], { timeout: 600000 }, () => resolve());
      currentChild = p;
      p.once("close", () => resolve());
    });

  const runQueue = async () => {
    if (playing) return;
    playing = true;
    try {
      while (queue.length > 0 && !cancelled) {
        const text = queue[0];
        const tmp = `/tmp/pi-speak-${Date.now()}-${Math.random().toString(36).slice(2)}.mp3`;
        const made = await genChunk(text, tmp);
        // 生成结果不可用(失败/被打断的半成品) → 立即清理
        const usable = made !== null && existsSync(tmp) && statSync(tmp).size >= 1000;
        if (!usable) {
          try { unlinkSync(tmp); } catch { /* ignore */ }
        }
        if (cancelled) break;
        if (!usable) {
          queue.shift();
          continue;
        }
        await playChunk(tmp);
        try { unlinkSync(tmp); } catch { /* ignore */ }
        if (cancelled) break;
        queue.shift(); // 这一段播完/被跳过, 进下一段
      }
    } finally {
      playing = false;
      currentChild = null;
    }
  };

  const enqueue = (text: string) => {
    const chunks: string[] = [];
    for (let i = 0; i < text.length; i += MAX_CHUNK) chunks.push(text.slice(i, i + MAX_CHUNK));
    // 新回复顶掉旧队列: 上次的还没读完(比如被跳过一段后又来了新回复), 直接换新的
    killAllAudio();
    cancelled = false;
    queue = chunks;
    void runQueue();
  };

  // ---------------- 控制通道: /tmp/pi-speak.ctl ----------------
  // 格式: "skip <ms>" 或 "stop <ms>" (ms = 指令时间戳, 用于去重)
  setInterval(() => {
    let raw: string;
    try {
      raw = readFileSync(CTL, "utf8").trim();
    } catch {
      return; // 文件不存在 → 无指令
    }
    const m = raw.match(/^(skip|stop)\s+(\d+)/);
    if (!m) return;
    const stamp = parseInt(m[2], 10);
    if (stamp <= lastCtlStamp) return;
    lastCtlStamp = stamp;
    if (m[1] === "stop") {
      cancelled = true;
      queue = [];
      killAllAudio();
      log("stop: 停止朗读, 等待下一次回复");
    } else {
      // skip: 杀掉当前段 → runQueue 循环自动播下一段; 已是最后一段则自然结束
      log("skip: 跳到下一段");
      killAllAudio();
    }
  }, 200);

  pi.on("agent_end", async (event, _ctx) => {
    if (event.willRetry) return; // retry will re-run; skip intermediate

    const messages = event.messages ?? [];
    // take ONLY the final assistant message (the last one that has text)
    let final: string | null = null;
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg.role !== "assistant") continue;
      const text = (msg.content ?? [])
        .filter((b) => b.type === "text")
        .map((b) => b.text)
        .join("\n")
        .trim();
      if (!text) continue;
      final = text;
      break;
    }
    if (final) enqueue(cleanForTTS(final));
  });
}
