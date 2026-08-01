# Pi 语音朗读（微软 TTS）

> 本模块属于 **Pi 语音闭环 (pi-voice)** 项目，见 [上级目录 README](../README.md)。

让 pi 用微软 TTS（晓晓音色）朗读最终回复。中英文都可以，自动清理 Markdown / emoji / 下划线，只读最终答案不读中间过程。

## 文件说明

| 文件 | 作用 |
|---|---|
| `speak.ts` | pi 扩展（语音朗读 + 文本净化），无需修改 |
| `install.sh` | 一键安装脚本（macOS） |
| `README.md` | 本说明 |

## 安装（目标电脑）

```bash
# 1. 前提：已安装 pi + node 24+（macOS）
# 2. 把仓库拷到目标电脑，然后：
cd pi-voice/voice-tts
bash install.sh
```

脚本会自动：
1. 安装 `edge-tts`（微软 TTS 命令行工具，pipx 或 pip）
2. 把 `speak.ts` 复制到 `~/.pi/agent/extensions/`
3. 验证语法

## 使用

1. 打开 pi，输入 `/reload`（或重启 pi）
2. 发消息 → pi 会用晓晓音色朗读**最终回复**

## 常用设置（环境变量）

| 环境变量 | 作用 | 示例 |
|---|---|---|
| `PI_SPEAK_VOICE` | 换音色 | `zh-CN-XiaoxiaoNeural`（默认，晓晓）、`en-US-AriaNeural`（英文）、`zh-CN-YunxiNeural`（男声） |
| `PI_SPEAK_OFF` | 临时关闭 | `1` |
| `EDGE_TTS_BIN` | 指定 edge-tts 路径（一般不用） | `/usr/local/bin/edge-tts` |

音色列表查询：`edge-tts --list-voices`

## 功能特性

- ✅ 只朗读最终答案（不读中间过程/工具调用）
- ✅ 自动清理：Markdown 符号、emoji、下划线、网址链接
- ✅ "晓晓/Xiaoxiao" 自动替换为 "我/I/My"（声音自称第一人称）
- ✅ 长回复自动分段（2000 字/段）
- ✅ 朗读失败静默跳过，不影响 pi 正常使用

## 注意

- **需要联网**：edge-tts 使用微软在线 TTS 服务
- 目前播放用 macOS 自带 `afplay`，**仅支持 macOS**；Windows/Linux 需自行替换播放命令（如 `ffplay` / `mpv`）
- 语音输入（听写）是系统功能，无需安装

## 故障排查

| 问题 | 解决 |
|---|---|
| /reload 后不朗读 | 确认扩展在 `~/.pi/agent/extensions/`；重启 pi 试试 |
| 报错找不到 edge-tts | `pipx ensurepath && exec $SHELL`，或设置 `EDGE_TTS_BIN` |
| 想完全关闭 | `export PI_SPEAK_OFF=1` |
| 声音不好听 | 换音色：`export PI_SPEAK_VOICE=en-US-AriaNeural` |
