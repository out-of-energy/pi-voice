# Whisper 语音输入法（macOS / Apple Silicon）

> 本模块属于 **Pi 语音闭环 (pi-voice)** 项目，见 [上级目录 README](../README.md)。

把 **MLX Whisper** 包装成系统级语音输入法：按热键说话，说完自动停止，转写文字直接输入到当前聚焦的应用（pi、微信、备忘录、任何能打字的地方）。

支持**中文 / 英文 / 中英混说**，识别效果远超 macOS 自带听写。

## 文件说明

| 文件 | 作用 |
|---|---|
| `init.lua` | Hammerspoon 配置（热键、录音、自动停止、转写、输入） |
| `vad_recorder.py` | WebRTC VAD 人声检测录音器（替代 silencedetect 音量阈值） |
| `whisper_daemon.py` | Whisper 常驻转写守护进程（模型加载一次，循环服务） |
| `install.sh` | 一键安装脚本 |
| `README.md` | 本说明 |

## 工作原理

```
⌃⌥Space → vad_recorder.py 录音(WebRTC VAD 人声检测)
        → 连续 0.9s 检测到人声才开始录(带预卷) → 说完静音 0.8s 自动停止
        → 守护进程(whisper_daemon.py, 模型常驻内存) 转写
          └─ 守护进程不可用时自动回退 CLI (mlx_whisper)
        → 文字自动输入当前应用
```

## 性能优化说明（守护进程）

每次转写重新加载模型需要 ~2.8s（还会受 HF Hub 网络检查影响，可随机卡 30s+）。
守护进程把模型**加载一次常驻内存**，后续每次转写只需纯推理（~1.8s），整体从 ~4.6s 降到 ~1.8s。

- 模型文件优先使用本地 HF 缓存（`~/.cache/huggingface/hub/`），零网络访问
- Hammerspoon 启动时自动拉起守护进程，每 120s 保活检查，掉线自动重启
- 日志：`/tmp/pi-whisper-daemon.log`；PID：`/tmp/pi-whisper-daemon.pid`
- 手动停止：`kill $(cat /tmp/pi-whisper-daemon.pid)`（重启 Hammerspoon 会自动拉起）

## 安装（目标电脑）

```bash
# 前提: Apple Silicon Mac + Homebrew
cd pi-voice/voice-input
bash install.sh
```

（或直接运行仓库根目录的 `bash install.sh` 一次性安装输入 + 输出）

脚本自动安装：Hammerspoon、ffmpeg、mlx-whisper（+ SOCKS 代理兼容）、
webrtcvad（`pipx runpip mlx-whisper install webrtcvad-wheels`，VAD 人声检测用）。

## 必须手动授权（安装后）

**系统设置 → 隐私与安全性：**

| 权限 | 作用 |
|---|---|
| 辅助功能 → Hammerspoon | 全局热键 + 向应用输入文字 |
| 麦克风 → Hammerspoon | 录音（未授权时会录到静音） |

## 使用

| 操作 | 效果 |
|---|---|
| 按 `⌃⌥Space` | 开始录音（屏幕提示"🎙 录音中…"） |
| 说话后停顿 0.8 秒 | 自动停止 → "⏳ 转写中…" → 文字自动输入 |
| 再按一次 `⌃⌥Space` | 取消本次录音 |
| 没说话（6 秒内无人声） | 自动取消，提示"没听到声音" |
| 咳嗽/环境声（语音过短） | 自动丢弃，不转写 |

## 配置（编辑 `~/.hammerspoon/init.lua`）

| 参数 | 默认 | 说明 |
|---|---|---|
| `LANG` | `"auto"` | 语言：`auto` 自动 / `"zh"` 强制中文（中英混说推荐） |
| 人声识别 | WebRTC VAD (aggress=2) | 识别"人声特征"而非音量：轻声可识别、电视/音乐/键盘不易误触发 |
| 开始判定 | 连续 0.9s 有人声 | 连续 3 个 0.3s 窗口各 ≥6/10 语音帧才算开始说话 |
| 停止判定 | 静音 0.8s | 停顿多久算说完（`TAIL_MS`，vad_recorder.py 内） |
| 最长录音 | 15s | `MAX_SEC`，vad_recorder.py 内 |
| 无语音取消 | 6s | 录音开始 6s 内未检测到人声自动取消 |
| 语音过短 | <0.45s 丢弃 | 疑似咳嗽/环境声，不转写 |

> 不再需要手动调静音阈值（`silencedetect noise=XXdB`）——VAD 按波形特征判别，与音量无关。

## 故障排查

| 问题 | 解决 |
|---|---|
| 按热键没反应 | 辅助功能权限未开；Hammerspoon 菜单栏图标 → Reload Config |
| "没录到声音" | 麦克风权限未开（Hammerspoon） |
| 转写失败/找不到模型 | 首次使用需联网下载模型（~1.6GB） |
| SOCKS 代理报错 | 已自动装 socksio；或运行 `pipx runpip mlx-whisper install socksio` |
| 中英混说丢语言 | `LANG = "zh"` |
| 键盘声误触发 | 连续敲击可能被当作说话；出现时再按一次 `⌃⌥Space` 取消 |

## 要求

- macOS（Apple Silicon，MLX 框架需要）
- 联网（首次下载模型、转写用本地模型无需联网）
- 与 `voice-tts` 模块（语音朗读）配合 = 完整语音对话闭环
