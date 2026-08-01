#!/bin/bash
# ============================================================
#  Pi 语音闭环 一键安装脚本 (语音输入 + 语音输出)
#  Pi Voice Suite one-click installer
# ============================================================
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==========================================="
echo "  Pi 语音闭环安装 | Pi Voice Suite Setup"
echo "==========================================="
echo ""
echo "  [模块 1/2] 语音输入法 (voice-input)"
bash "$DIR/voice-input/install.sh"

echo ""
echo "  [模块 2/2] 语音朗读 (voice-tts)"
bash "$DIR/voice-tts/install.sh"

echo ""
echo "==========================================="
echo "  🎉 全部安装完成！"
echo "==========================================="
echo ""
echo "  还需手动授权 (系统设置 → 隐私与安全性):"
echo "    1. 辅助功能 → Hammerspoon   (全局热键 + 输入文字)"
echo "    2. 麦克风   → Hammerspoon   (录音)"
echo ""
echo "  使用:"
echo "    ⌃⌥Space 说话 → 文字输入当前应用 → pi 回复 → 晓晓朗读"
echo ""
echo "  文档: 见 README.md 及各模块 README.md"
