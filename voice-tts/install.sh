#!/bin/bash
# ============================================================
#  pi 微软语音朗读 一键安装脚本 (macOS)
#  Pi Microsoft TTS (Edge TTS) one-click installer
# ============================================================
set -e

echo "==========================================="
echo "  Pi 语音朗读安装 | Pi Voice Setup"
echo "==========================================="

# ---------- 1. 安装 edge-tts ----------
echo ""
echo "[1/3] 检查 edge-tts (微软 TTS 命令行工具)..."
if command -v edge-tts >/dev/null 2>&1; then
	echo "      ✅ 已安装: $(command -v edge-tts)"
else
	echo "      未安装，正在安装..."
	# 优先用 pipx，没有则用 pip
	if command -v pipx >/dev/null 2>&1; then
		pipx install edge-tts
	elif command -v pip3 >/dev/null 2>&1; then
		pip3 install --user edge-tts
	else
		echo "      ❌ 没有 pipx / pip3，请先安装: brew install pipx"
		exit 1
	fi
	# 确保 ~/.local/bin 在 PATH 里
	if ! command -v edge-tts >/dev/null 2>&1; then
		echo "      尝试 pipx ensurepath ..."
		command -v pipx >/dev/null 2>&1 && pipx ensurepath
		export PATH="$HOME/.local/bin:$PATH"
	fi
	if ! command -v edge-tts >/dev/null 2>&1; then
		echo "      ❌ 还是找不到 edge-tts，请手动执行: pipx ensurepath && exec \$SHELL"
		echo "         或安装后设置 EDGE_TTS_BIN 指向 edge-tts 完整路径"
		exit 1
	fi
	echo "      ✅ edge-tts 安装完成"
fi

# ---------- 2. 复制扩展 + skill ----------
echo ""
echo "[2/3] 复制 speak.ts 和静音 skill 到 pi 目录..."
EXT_DIR="$HOME/.pi/agent/extensions"
SKILL_DIR="$HOME/.pi/agent/skills/pi-voice-mute"
mkdir -p "$EXT_DIR" "$SKILL_DIR"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/speak.ts" "$EXT_DIR/speak.ts"
echo "      ✅ 已安装到 $EXT_DIR/speak.ts"
cp "$SCRIPT_DIR/skills/pi-voice-mute/SKILL.md" "$SKILL_DIR/SKILL.md"
echo "      ✅ 已安装到 $SKILL_DIR/SKILL.md"

# ---------- 3. 验证 ----------
echo ""
echo "[3/3] 验证..."
node --experimental-strip-types --check "$EXT_DIR/speak.ts" 2>/dev/null && echo "      ✅ 扩展语法正确" || echo "      ⚠️ 无法验证语法(需要 node 24+)，忽略"

echo ""
echo "==========================================="
echo "  🎉 安装完成！"
echo "==========================================="
echo ""
echo "  使用步骤:"
echo "    1. 打开 pi，输入 /reload (或完全重启 pi)"
echo "    2. 随便发一条消息 → pi 会用微软 TTS 朗读最终回复"
echo ""
echo "  静音开关 (说一句就行，立即生效，无需 reload):"
echo "    \"静音\" / \"mute pi\"     →  pi 停止朗读"
echo "    \"恢复朗读\" / \"unmute\"  →  pi 重新朗读"
echo "    (原理: 写/删 ~/.pi/speak.mute，每次回复前检查)"
echo ""
echo "  可选设置 (环境变量):"
echo "    PI_SPEAK_VOICE=zh-CN-XiaoxiaoNeural   换音色 (默认晓晓，中英都好)"
echo "    PI_SPEAK_VOICE=en-US-AriaNeural       换英文女声"
echo "    PI_SPEAK_OFF=1                        硬关闭 (启动前设置，需重启 pi)"
echo ""
echo "  要求: macOS + pi (https://github.com/earendil/pi) + 联网 (edge-tts 走微软服务)"
echo ""
