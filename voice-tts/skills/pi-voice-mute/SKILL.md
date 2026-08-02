---
name: pi-voice-mute
description: Toggle pi's voice output (TTS 朗读) on/off instantly, no reload needed. Load when the user says: mute pi, silence pi, stop pi speaking, 静音, 别说话, 别念了, 关掉朗读, 不要再朗读, unmute, 恢复朗读, 打开朗读, or asks why pi is/isn't speaking.
---

# Pi Voice Mute (语音朗读开关)

Pi 的朗读由扩展 `~/.pi/agent/extensions/speak.ts` 实现（微软 edge-tts + afplay）。
它**每次回复前**检查静音文件，所以开关**立刻生效，无需 `/reload`、无需重启**。
状态存在文件里，重启 pi 后依然保持。

## 静音（关掉朗读）

```bash
echo 1 > ~/.pi/speak.mute
# 立即停掉正在朗读的声音（可选但推荐）
echo "stop $(date +%s%3N)" > /tmp/pi-speak.ctl
```

回复用户：已静音，pi 从下一条回复起不再朗读（正在播的也停了）。

## 恢复朗读（取消静音）

```bash
rm -f ~/.pi/speak.mute
```

回复用户：已恢复，pi 下一条回复会重新朗读。

## 查看当前状态

```bash
[ -f ~/.pi/speak.mute ] && echo "muted" || echo "speaking"
```

## 注意

- 静音文件默认 `~/.pi/speak.mute`，可用环境变量 `PI_SPEAK_MUTE_FILE` 覆盖（一般不用）。
- 硬关闭（永久卸载式）：`export PI_SPEAK_OFF=1` 需要在**启动 pi 前**设置，改 env 后必须重启 pi 才生效——优先用本技能的静音文件方案。
- 排查朗读问题看日志 `/tmp/pi-speak.log`。
- 长回复朗读控制热键（Hammerspoon）：`⌃⌥K` 跳下一段、`⌃⌥I` 停止本次朗读（不持久）；本技能提供的是**持久**开关。
