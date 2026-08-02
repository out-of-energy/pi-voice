# Pi 语音朗读（微软 TTS）

> 本模块属于 **Pi 语音闭环 (pi-voice)** 项目，见 [上级目录 README](../README.md)。

让 pi 用微软 TTS（晓晓音色）朗读最终回复。中英文都可以，自动清理 Markdown / emoji / 下划线，只读最终答案不读中间过程。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `speak.ts` | pi 扩展（语音朗读 + 文本净化 + 静音开关），无需修改 |
| `skills/pi-voice-mute/SKILL.md` | 静音开关 skill（对 pi 说“静音”/“恢复朗读”即可切换，无需 reload） |
| `install.sh` | 一键安装脚本（macOS，含扩展 + skill） |
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
2. 把 `speak.ts` 复制到 `~/.pi/agent/extensions/`，把 `pi-voice-mute` skill 复制到 `~/.pi/agent/skills/`
3. 验证语法

## 使用

1. 打开 pi，输入 `/reload`（或重启 pi）
2. 发消息 → pi 会用晓晓音色朗读**最终回复**
3. 长回复分段朗读时，可随时打断/跳过（见下）
4. 想静音/恢复：直接对 pi 说 **“静音”** 或 **“恢复朗读”**（见[静音开关](#静音开关说一句就行)）

## 朗读控制（打断 / 跳到下一段）

长回复按 2000 字/段排队朗读。通过 **Hammerspoon 全局热键**控制
（需要已安装 voice-input 模块的 Hammerspoon 配置）：

| 热键 | 效果 |
| --- | --- |
| `⌃⌥K` | **跳到下一段**（当前段停止，直接读下一段；全部读完即等下一次回复） |
| `⌃⌥I` | **停止朗读**（清空队列，直到 pi 下一次回复才再读） |

工作原理：Hammerspoon 写入 `/tmp/pi-speak.ctl`，speak.ts 每 200ms 轮询响应——
即使你切到其他应用（pi 不在前台）也能控制，因为热键是全局的。
运行日志写入 `/tmp/pi-speak.log`（不刷 TUI 屏幕），排查问题看这里。

> 没有安装 Hammerspoon 时，可手动写控制文件：`echo "stop $(date +%s%3N)" > /tmp/pi-speak.ctl`

## 静音开关（说一句就行）

| 对 pi 说 | 效果 |
| --- | --- |
| **“静音”** / “mute pi” / “别说话” | 立即停止朗读，之后 pi 不再朗读（重启 pi 也保持） |
| **“恢复朗读”** / “unmute” | 重新开始朗读 |

- 原理：`pi-voice-mute` skill 写/删 `~/.pi/speak.mute`，speak.ts **每次回复前检查**——立即生效，**无需 reload**
- 手动等价命令：`echo 1 > ~/.pi/speak.mute`（静音）/ `rm -f ~/.pi/speak.mute`（恢复）
- 与 `⌃⌥I` 的区别：`⌃⌥I` 只停当前这次朗读；静音开关**持久**（跨回复、跨重启）
- 也可手动触发 skill：`/skill:pi-voice-mute`

## 常用设置（环境变量）

| 环境变量 | 作用 | 示例 |
| --- | --- | --- |
| `PI_SPEAK_VOICE` | 换音色 | `zh-CN-XiaoxiaoNeural`（默认，晓晓）、`en-US-AriaNeural`（英文）、`zh-CN-YunxiNeural`（男声） |
| `PI_SPEAK_OFF` | 硬关闭（启动前设置，需重启 pi） | `1` |
| `~/.pi/speak.mute` | **静音开关**（文件，每次回复前检查，**无需 reload**） | `echo 1 > ~/.pi/speak.mute` 静音 / `rm -f ~/.pi/speak.mute` 恢复 |
| `EDGE_TTS_BIN` | 指定 edge-tts 路径（一般不用） | `/usr/local/bin/edge-tts` |
| `PI_SPEAK_MUTE_FILE` | 自定义静音文件路径（一般不用） | `/path/to/mute` |
| `PI_SPEAK_MAX_CHUNK` | 每段最大字符数（默认 2000，改小=更快出第一句、分段更碎） | `500` |

音色列表查询：`edge-tts --list-voices`

## 功能特性

- ✅ 只朗读最终答案（不读中间过程/工具调用）
- ✅ 自动清理：Markdown 符号、emoji、下划线、网址链接
- ✅ "晓晓/Xiaoxiao" 自动替换为 "我/I/My"（声音自称第一人称）
- ✅ 长回复自动分段（2000 字/段）
- ✅ 可打断：`⌃⌥K` 跳到下一段、`⌃⌥I` 停止朗读（Hammerspoon 全局热键，见上）
- ✅ 静音开关：说“静音”/“恢复朗读”，或直接写/删 `~/.pi/speak.mute`，无需 reload
- ✅ 新回复自动顶掉未读完的旧回复
- ✅ 朗读失败静默跳过，不影响 pi 正常使用

## 注意

- **需要联网**：edge-tts 使用微软在线 TTS 服务
- 目前播放用 macOS 自带 `afplay`，**仅支持 macOS**；Windows/Linux 需自行替换播放命令（如 `ffplay` / `mpv`）
- 语音输入（听写）是系统功能，无需安装

## 故障排查

| 问题 | 解决 |
| --- | --- |
| /reload 后不朗读 | 确认扩展在 `~/.pi/agent/extensions/`；重启 pi 试试 |
| 报错找不到 edge-tts | `pipx ensurepath && exec $SHELL`，或设置 `EDGE_TTS_BIN` |
| 想临时静音（立即生效） | `echo 1 > ~/.pi/speak.mute`（再 `echo "stop $(date +%s%3N)" > /tmp/pi-speak.ctl` 可立刻停掉正在播的） |
| 想恢复朗读 | `rm -f ~/.pi/speak.mute` |
| 想完全关闭（永久卸载式） | `export PI_SPEAK_OFF=1` 后重启 pi |
| 声音不好听 | 换音色：`export PI_SPEAK_VOICE=en-US-AriaNeural` |
