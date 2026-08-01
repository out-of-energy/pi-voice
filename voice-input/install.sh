#!/bin/bash
# ============================================================
#  Whisper 语音输入法 一键安装脚本 (macOS / Apple Silicon)
#  Whisper Voice Input Method one-click installer
# ============================================================
set -e

echo "==========================================="
echo "  Whisper 语音输入法安装 | Voice Input Setup"
echo "==========================================="

# ---------- 0. 检查芯片 ----------
if [ "$(uname -m)" != "arm64" ]; then
  echo "❌ mlx-whisper 需要 Apple Silicon (M1/M2/M3/M4) 芯片"
  exit 1
fi

# ---------- 1. Hammerspoon ----------
echo ""
echo "[1/4] 检查 Hammerspoon..."
if [ -d "/Applications/Hammerspoon.app" ]; then
  echo "      ✅ 已安装"
else
  echo "      安装中..."
  brew install --cask hammerspoon
fi

# ---------- 2. ffmpeg ----------
echo ""
echo "[2/4] 检查 ffmpeg..."
if command -v ffmpeg >/dev/null 2>&1; then
  echo "      ✅ 已安装: $(command -v ffmpeg)"
else
  echo "      安装中..."
  brew install ffmpeg
fi

# ---------- 3. mlx-whisper ----------
echo ""
echo "[3/4] 检查 mlx-whisper..."
if command -v mlx_whisper >/dev/null 2>&1; then
  echo "      ✅ 已安装: $(command -v mlx_whisper)"
else
  echo "      安装中 (首次使用会下载模型，约 1.6GB，需联网)..."
  if command -v pipx >/dev/null 2>&1; then
    pipx install mlx-whisper
  elif command -v pip3 >/dev/null 2>&1; then
    pip3 install --user mlx-whisper
  else
    echo "      ❌ 需要 pipx 或 pip3: brew install pipx"
    exit 1
  fi
  export PATH="$HOME/.local/bin:$PATH"
  command -v pipx >/dev/null 2>&1 && pipx ensurepath || true
fi

# ---------- 3.5 socks 代理兼容 ----------
echo ""
echo "[3.5] SOCKS 代理兼容处理..."
pipx runpip mlx-whisper install socksio 2>/dev/null && echo "      ✅ socksio 已装" || true

# ---------- 4. 复制配置并启动 ----------
echo ""
echo "[4/4] 安装配置..."
mkdir -p "$HOME/.hammerspoon"
cp "$(dirname "$0")/init.lua" "$HOME/.hammerspoon/init.lua"
cp "$(dirname "$0")/whisper_daemon.py" "$HOME/.hammerspoon/whisper_daemon.py"
echo "      ✅ 已安装到 ~/.hammerspoon/ (init.lua + whisper_daemon.py)"
open -a Hammerspoon 2>/dev/null || true

echo ""
echo "==========================================="
echo "  🎉 安装完成！"
echo "==========================================="
echo ""
echo "  必须手动授权 (系统设置 → 隐私与安全性):"
echo "    1. 辅助功能 → 打开 Hammerspoon   (全局热键 + 输入文字)"
echo "    2. 麦克风   → 打开 Hammerspoon   (录音)"
echo ""
echo "  使用:"
echo "    按 ⌃⌥Space 说话 → 说完停顿自动停止 → 文字自动输入当前应用"
echo "    再按一次 ⌃⌥Space = 取消"
echo ""
echo "  首次转写会自动下载模型 whisper-large-v3-turbo (约1.6GB)"
echo "  修改转写语言: 编辑 ~/.hammerspoon/init.lua 里的 LANG"
echo "    (auto=自动检测 / zh=强制中文，中英混说推荐)"
echo ""
