#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pi-voice 麦克风音量校准工具
===========================
按提示朗读几句，自动统计「你的说话音量」与「环境噪声」，给出可靠的
silencedetect 静音阈值，避免语音输入法听不到你 / 被环境噪音误触发。

用法:
    python3 calibrate.py

流程:
    4 轮采样(环境噪声 / 正常音量 / 中英混说 / 小声)
    → 逐帧统计 → 推荐阈值 → 可选自动写入配置(init.lua)

录音方式:
    环境噪声轮固定录 10 秒(太短采不到瞬时噪声峰, 容易低估环境);
    朗读轮**手动停止**(按回车开始, 说完再按回车停止, 超 15s 自动终止)。
    手动停止不用猜静音阈值, 最可靠, 且录音不夹带大段空白噪声, 统计更准。

原理:
    ffmpeg 录音, 逐 50ms 帧算 RMS dB(与 ffmpeg volumedetect 同量纲,
    0dB = 满幅):
      噪声底   = 全部帧的 8% 分位
      噪声峰   = 噪声帧的 90% 分位  (环境瞬时最响)
      说话最低 = 说话帧的 5% 分位   (你最轻的一句话)
    推荐阈值 = 噪声峰与说话最低的中点 —— 高于环境噪声峰值(噪音不会误触发)、
    低于最低说话音量(不会漏听), 两边各留一半余量。

    余量 < 6dB 时环境噪声已逼近你的最低说话音量, 工具会提示你改善环境或
    靠近麦克风后重跑。

依赖: 仅 Python 标准库 + ffmpeg(已随 voice-input 安装)
"""
import math
import os
import re
import select
import shutil
import struct
import subprocess
import sys
import time
import wave

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
TMP_DIR = "/tmp/pi-calib"

# 朗读轮录音超时自动终止(秒), 防止忘记按回车停止
default_max = 15
MAX_SEC = int(os.environ.get("PI_CALIB_MAX_SEC", str(default_max)))

# 需要同步的 init.lua 副本(按顺序探测, 存在的都会被询问是否更新)
INIT_LUA_COPIES = [
    os.path.expanduser("~/.hammerspoon/init.lua"),
    os.path.expanduser("~/sandbox/pi-voice/voice-input/init.lua"),
    os.path.expanduser("~/sandbox/pi-voice-input/init.lua"),
]

NOISE_SAMPLE_SEC = int(os.environ.get("PI_CALIB_NOISE_SEC", "10"))

ROUNDS = [
    ("环境噪声", None),  # 先采样环境, 让后续朗读轮有参照
    ("正常音量", "今天天气不错，我们去公园散步吧。"),
    ("中英混说", "帮我查一下 OpenAI 最新发布的 whisper 模型。"),
    ("小声",     "麻烦你了，谢谢。"),
]


# ---------------------------------------------------------------- 录音

def record(path, fixed_sec=None):
    """录音到 path。fixed_sec 给定时录满该时长; 否则按回车手动停止(超时自动停)。"""
    os.makedirs(TMP_DIR, exist_ok=True)
    cap = fixed_sec if fixed_sec is not None else MAX_SEC
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "avfoundation", "-i", ":0",
           "-ac", "1", "-t", str(cap), path]
    if not os.path.exists(FFMPEG):
        print("❌ 找不到 ffmpeg: %s" % FFMPEG)
        sys.exit(1)
    with open(os.devnull, "w") as lf:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=lf)
    if fixed_sec is not None:
        try:
            p.wait(timeout=cap + 5)
        except subprocess.TimeoutExpired:
            p.kill()
    else:
        # 手动停止: 按回车结束(或超时自动终止)
        start = time.time()
        while time.time() - start < cap:
            r, _, _ = select.select([sys.stdin], [], [], 0.2)
            if r:
                sys.stdin.readline()
                break
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    return os.path.exists(path) and os.path.getsize(path) > 1000


# ---------------------------------------------------------------- 分析

def frame_dbs(data, rate, ch, sw, frame_ms=50):
    """按 50ms 帧算 RMS dB, 返回帧列表(0dB=满幅, 与 ffmpeg volumedetect 同量纲)。"""
    nbytes = rate * frame_ms // 1000 * ch * sw
    out = []
    for i in range(0, len(data) - nbytes + 1, nbytes):
        chunk = data[i:i + nbytes]
        n = len(chunk) // sw // ch
        if n == 0:
            continue
        if sw == 2:
            samples = struct.unpack("<%dh" % (n * ch), chunk)
        elif sw == 1:
            samples = [x - 128 for x in struct.unpack("<%dB" % (n * ch), chunk)]
        else:
            raise ValueError("不支持的位深: %d 字节/采样" % sw)
        s = sum(x * x for x in samples) / len(samples)
        out.append(20.0 * math.log10(math.sqrt(s) / 32768.0) if s > 0 else -120.0)
    return out


def analyze(path):
    """分析 WAV, 返回统计 dict。"""
    w = wave.open(path, "rb")
    data = w.readframes(w.getnframes())
    rate, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
    w.close()
    dbs = frame_dbs(data, rate, ch, sw)
    if not dbs:
        return None
    srt = sorted(dbs)
    noise_floor = srt[int(len(srt) * 0.08)]
    noise_frames = [d for d in dbs if d <= noise_floor + 3.0]
    speech_frames = [d for d in dbs if d > noise_floor + 6.0]
    noise_peak = (sorted(noise_frames)[int(len(noise_frames) * 0.90)]
                  if noise_frames else noise_floor)
    speech = None
    if len(speech_frames) * 0.05 >= 0.35:  # 说话 ≥ 0.35s 才算有效
        sf = sorted(speech_frames)
        speech = {
            "dur": len(speech_frames) * 0.05,
            "mean": sum(speech_frames) / len(speech_frames),
            "min": sf[int(len(sf) * 0.05)],
            "peak": sf[int(len(sf) * 0.95)],
        }
    return {"noise_floor": noise_floor, "noise_peak": noise_peak,
            "speech": speech, "max_db": max(dbs), "dur": len(dbs) * 0.05}


def fmt_db(x):
    return "%+.0f dB" % x


# ---------------------------------------------------------------- 交互

def ask(prompt, default="y"):
    try:
        r = input(prompt + " [%s] " % ("Y/n" if default == "y" else "y/N"))
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    r = r.strip().lower()
    if not r:
        return default
    return "y" if r in ("y", "yes", "是", "对") else "n"


def run_round(idx, total, title, text):
    print("\n" + "═" * 56)
    print("第 %d/%d 轮 · %s" % (idx, total, title))
    if text:
        print("请朗读:  %s" % text)
        input("   [按回车开始录音，说完再按回车停止（超 15s 自动停）]")
    else:
        input("   [按回车开始采样环境噪声（%d 秒，请不要说话）]" % NOISE_SAMPLE_SEC)
    while True:
        wav = os.path.join(TMP_DIR, "round%d.wav" % idx)
        ok = record(wav, fixed_sec=NOISE_SAMPLE_SEC if text is None else None)
        if not ok:
            print("❌ 录音失败(文件为空)。检查麦克风权限: 系统设置 → 隐私与安全性 → 麦克风 → Hammerspoon/终端")
            if ask("重试本轮? ", "y") != "y":
                return None
            continue
        try:
            r = analyze(wav)
        except Exception as exc:  # noqa: BLE001
            print("❌ 分析失败: %s" % exc)
            return None
        if text is None:
            # 环境噪声轮: 固定时长, 正常不应有说话声
            print("✅ 环境采样完成 · 噪声底 %s · 噪声峰 %s · 峰值 %s"
                  % (fmt_db(r["noise_floor"]), fmt_db(r["noise_peak"]), fmt_db(r["max_db"])))
            if r["noise_peak"] > -42:
                print("   ⚠️ 环境较吵(噪声峰 > -42dB)。建议关掉电视/音乐或靠近麦克风, 否则阈值会偏保守。")
            return r
        if r["speech"]:
            sp = r["speech"]
            print("✅ 录音 %.1fs · 说话 %.1fs · 峰值 %s · 均值 %s · 最低 %s · 噪声底 %s"
                  % (r["dur"], sp["dur"], fmt_db(sp["peak"]), fmt_db(sp["mean"]),
                     fmt_db(sp["min"]), fmt_db(r["noise_floor"])))
        else:
            print("⚠️ 没检测到说话声(录音 %.1fs, 噪声底 %s, 噪声峰 %s)。"
                  % (r["dur"], fmt_db(r["noise_floor"]), fmt_db(r["noise_peak"])))
            if ask("没听清/没检测到, 重录本轮?", "y") != "y":
                return r
            continue
        return r


# ---------------------------------------------------------------- 主流程

def main():
    print("🎤 pi-voice 麦克风音量校准")
    print("  请保持与平时使用语音输入时相同的距离和音量。")
    print("  共 %d 轮: 第 1 轮采环境噪声, 之后 3 轮你朗读。随时 Ctrl+C 退出。\n" % len(ROUNDS))

    results = []
    for i, (title, text) in enumerate(ROUNDS, 1):
        r = run_round(i, len(ROUNDS), title, text)
        if r is None:
            results.append(None)
            continue
        results.append(r)

    valid = [r for r in results if r is not None and r["speech"]]
    noises = [r["noise_peak"] for r in results if r is not None]
    if not valid or not noises:
        print("\n❌ 没有任何一轮检测到说话声。请检查:")
        print("   1. 系统设置 → 隐私与安全性 → 麦克风 → 已授权终端/Hammerspoon")
        print("   2. 默认输入设备是否是你要用的麦克风(系统设置 → 声音 → 输入)")
        sys.exit(1)

    worst_noise = max(noises)                      # 最吵环境下的噪声峰值
    softest = min(r["speech"]["min"] for r in valid)  # 最轻的一句话
    margin = softest - worst_noise
    recommended = int(round((worst_noise + softest) / 2))
    recommended = max(-55, min(-15, recommended))

    print("\n" + "═" * 56)
    print("════════════ 校准结果 ════════════")
    print("  环境噪声峰值(最吵时):  %s" % fmt_db(worst_noise))
    print("  你的最低说话音量:      %s" % fmt_db(softest))
    print("  你的说话均值:          %s" % fmt_db(sum(r["speech"]["mean"] for r in valid) / len(valid)))
    print("  你的说话峰值:          %s" % fmt_db(max(r["speech"]["peak"] for r in valid)))
    print("  余量(最低说话-噪声峰): %+.0f dB  %s"
          % (margin, "✅ 理想" if margin >= 6 else ("⚠️ 可用,建议靠近麦克风" if margin >= 3 else "❌ 无可靠阈值")))
    if margin < 6:
        print("  \n  ⚠️ 余量 < 6dB: 噪声峰和轻声之间没有足够的间隔, 任何阈值都只有 <3dB 的")
        print("     安全余量。真实使用中环境噪声波动(键盘/空调/窗外/电视)很容易冲破阈值,")
        print("     导致录音不自动停止(等满 25s)或误触发。")
        print("     ⚠️ 请务必先按 ⌃⌥Space 做真实场景验证, 确认能自动停、不误触发, 再决定是否写入。")
        print("     建议重跑: 1) 在平时使用的时间段跑(不要特意安静); 2) 小声轮用你真实的最小音量;")
        print("     3) 环境噪声轮期间正常活动(敲键盘/开关设备)。")
    print("\n  → 推荐静音阈值:  noise=%ddB" % recommended)
    print("    (高于噪声峰 → 噪音不误触发; 低于最低说话 → 不漏听)")
    print("═" * 56)

    if ask("\n是否写入配置(init.lua 的 silencedetect 阈值)?") != "y":
        print("未修改配置。手动修改: 把 init.lua 中 silencedetect 的阈值改为 noise=%ddB" % recommended)
        return

    patched = []
    for path in INIT_LUA_COPIES:
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        new, n = re.subn(r"(silencedetect=noise=)-?\d+dB", r"\g<1>%ddB" % recommended, src)
        if n == 0:
            print("  - 跳过 %s (未找到 silencedetect 阈值)" % path)
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
        print("  ✅ 已更新 %s  → noise=%ddB" % (path, recommended))
        patched.append(path)

    if patched:
        print("\n完成! 请让配置生效: Hammerspoon 菜单栏图标 → Reload Config")
        print("然后按 ⌃⌥Space 说话测试。")
        if ask("是否同步更新 README 配置表?") == "y":
            for rp in ["~/sandbox/pi-voice/voice-input/README.md", "~/sandbox/pi-voice-input/README.md"]:
                p = os.path.expanduser(rp)
                if not os.path.isfile(p):
                    continue
                with open(p, "r", encoding="utf-8") as f:
                    src = f.read()
                src = re.sub(r"`-?\d+dB`", "`%ddB`" % recommended, src, count=1)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(src)
                print("  ✅ 已更新 %s" % p)


if __name__ == "__main__":
    main()
