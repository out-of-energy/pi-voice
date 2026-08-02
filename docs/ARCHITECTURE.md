# Pi 语音闭环 · 架构图

> 完整数据流：**说 → pi 理解并回复 → pi 朗读出来**，外加两条旁路控制通道。

```mermaid
flowchart LR
    subgraph IN["语音输入 voice-input"]
        HK["⌃⌥Space 热键<br/>Hammerspoon init.lua"]
        FF["ffmpeg 麦克风采集<br/>16k 单声道 PCM"]
        VAD["WebRTC VAD 人声检测<br/>vad_recorder.py"]
        WH["Whisper 常驻守护进程<br/>whisper_daemon.py :18765"]
        CL["CLI 回退<br/>mlx_whisper 本地模型"]
        HK --> FF --> VAD --> WH
        WH -->|"守护不可用"| CL
        VAD -->|"exit 2/3 (无语音/太短)"| DR["丢弃, 不转写"]
    end

    subgraph APP["文字上屏"]
        T["当前应用 / pi"]
    end
    WH -->|"转写文本"| T
    CL -->|"转写文本"| T

    subgraph OUT["语音输出 voice-tts"]
        EX["speak.ts 扩展<br/>agent_end 事件"]
        MU{"静音?<br/>~/.pi/speak.mute"}
        ET["edge-tts 微软 TTS<br/>晓晓音色"]
        AP["afplay 播放"]
        EX --> MU
        MU -->|"否"| ET --> AP
        MU -->|"是"| SK["跳过朗读"]
    end

    T -->|"pi 回复 (Markdown)"| EX

    subgraph CTL["旁路控制"]
        HK2["⌃⌥K 跳到下一段<br/>⌃⌥I 停止朗读<br/>(Hammerspoon)"]
        HK2 -->|"写 /tmp/pi-speak.ctl"| AP
        SKILL["pi-voice-mute skill<br/>说\"静音\"/\"恢复朗读\""]
        SKILL -->|"写/删 ~/.pi/speak.mute"| MU
    end

    style HK fill:#ffe0b2
    style FF fill:#ffe0b2
    style VAD fill:#ffe0b2
    style WH fill:#ffe0b2
    style CL fill:#ffecb3
    style EX fill:#c8e6c9
    style MU fill:#fff59d
    style ET fill:#c8e6c9
    style AP fill:#c8e6c9
```

## 数据流说明

### ① 语音输入（voice-input）

- **⌃⌥Space 热键**（Hammerspoon `init.lua`）→ 启动 `vad_recorder.py`
- `vad_recorder.py` 用 **ffmpeg** 实时采集麦克风（16k 单声道），逐 30ms 帧喂 **WebRTC VAD** 做"人声检测"（替代旧版 silencedetect 音量阈值）：连续 3 个窗口检测到语音才开始录（带 0.9s 预卷不吞字头），说完静音 0.8s 自动停
- 录音完成后优先走 **Whisper 常驻守护进程**（`whisper_daemon.py`，模型热载，转写 ~1.9s）；守护不可用自动回退 **CLI**（`mlx_whisper` 本地模型，零网络）
- 转写文本直接 **keyStrokes 上屏**到当前应用（包括 pi）

### ② 语音输出（voice-tts）

- pi 回复后触发 `speak.ts` 扩展的 **agent_end** 事件
- 先检查静音文件 `~/.pi/speak.mute`（内容 `1` 即静音，**立即生效无需 reload**）
- 未静音 → 净化 Markdown/emoji → **edge-tts**（微软在线 TTS，晓晓音色）生成 mp3 → **afplay** 播放
- 长回复按 2000 字分段排队朗读

### ③ 旁路控制

- **⌃⌥K / ⌃⌥I**（Hammerspoon 全局热键）→ 写 `/tmp/pi-speak.ctl`，speak.ts 每 200ms 轮询 → 跳段/停止（只影响当前这次朗读）
- **pi-voice-mute skill**（对 pi 说"静音"/"恢复朗读"）→ 写/删 `~/.pi/speak.mute` → **持久开关**（跨回复、跨重启）

## 关键文件

| 模块 | 文件 | 职责 |
| --- | --- | --- |
| 输入 | `voice-input/init.lua` | 热键、录音调度、转写调度、守护进程保活 |
| 输入 | `voice-input/vad_recorder.py` | WebRTC VAD 人声检测录音（ffmpeg 采集） |
| 输入 | `voice-input/whisper_daemon.py` | Whisper 常驻转写 HTTP 服务 (:18765) |
| 输出 | `voice-tts/speak.ts` | agent_end → 净化 → edge-tts → afplay（含静音开关/ctl 控制） |
| 输出 | `voice-tts/skills/pi-voice-mute/SKILL.md` | 静音/恢复朗读的 agent 技能 |
| 安装 | `install.sh` × 3 | 一键安装各模块 |
