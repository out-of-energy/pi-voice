# Pi 语音闭环 (Pi Voice Suite)

让 **pi** 拥有完整的语音对话能力：**说 → pi 理解并回复 → pi 朗读出来**。

| 模块 | 功能 | 说明 |
|---|---|---|
| [`voice-input/`](voice-input/) | 语音**输入** | 任意应用内按热键说话 → Whisper 转写 → 文字上屏（⌃⌥Space） |
| [`voice-tts/`](voice-tts/) | 语音**输出** | pi 回复自动用微软 TTS（晓晓）朗读 |

## 目录结构

```
pi-voice/
├── install.sh          # 一键安装全部
├── voice-input/        # 语音输入法 (Hammerspoon + ffmpeg + Whisper 常驻守护进程)
│   ├── init.lua            # 热键/录音/自动停止/转写/输入
│   ├── whisper_daemon.py   # Whisper 常驻转写服务 (模型加载一次, 4.6s→1.9s)
│   ├── install.sh
│   └── README.md
└── voice-tts/          # 语音朗读 (pi 扩展 + edge-tts 晓晓)
    ├── speak.ts            # pi 扩展 (朗读 + 文本净化)
    ├── install.sh
    └── README.md
```

## 快速安装（目标电脑）

```bash
# 前提: Apple Silicon Mac + Homebrew + 已安装 pi (node 24+)
cd pi-voice
bash install.sh
```

或分开安装：`bash voice-input/install.sh` / `bash voice-tts/install.sh`。

安装后需手动授权（系统设置 → 隐私与安全性）：
1. **辅助功能 → Hammerspoon**（热键 + 输入文字）
2. **麦克风 → Hammerspoon**（录音）

## 使用

```text
你说话 ──⌃⌥Space──▶ 语音输入法转写 ──▶ pi ──▶ 晓晓朗读回复
```

| 操作 | 效果 |
|---|---|
| 按 `⌃⌥Space` 说话 | 说完停顿自动停止 → 文字输入当前应用 |
| 再按一次 `⌃⌥Space` | 取消录音 |
| pi 回复后 | 自动朗读最终答案（中英均可） |
| `⌃⌥K` | 跳到下一段朗读（长回复快速跳过） |
| `⌃⌥I` | 停止朗读（下次回复再读） |

## 各模块文档

- [语音输入法完整文档 → voice-input/README.md](voice-input/README.md)
  - 热键 `⌃⌥Space`，支持中英混说，`LANG` 可强制中文
  - Whisper 常驻守护进程：转写 ~1.9s（优化前 ~4.6s），日志 `/tmp/pi-whisper-daemon.log`
- [语音朗读完整文档 → voice-tts/README.md](voice-tts/README.md)
  - 晓晓音色，自动净化 Markdown/emoji，只读最终答案
  - 换音色：`export PI_SPEAK_VOICE=en-US-AriaNeural`

## 常见问题

| 问题 | 解决 |
|---|---|
| 热键没反应 | 检查辅助功能/麦克风授权；Hammerspoon 菜单栏 → Reload Config |
| 转写慢 | 守护进程日志 `/tmp/pi-whisper-daemon.log`；`kill $(cat /tmp/pi-whisper-daemon.pid)` 后重启 Hammerspoon |
| pi 不朗读 | pi 里 `/reload`；或 `export PI_SPEAK_OFF=1` 关闭 |
| 中英混说丢语言 | `voice-input/init.lua` 里 `LANG = "zh"` |

## 技术栈

- **输入**：Hammerspoon (Lua) + ffmpeg (avfoundation) + MLX Whisper (Apple Silicon)
- **输出**：pi 扩展 (TypeScript) + edge-tts (微软在线 TTS) + afplay
