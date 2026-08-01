#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pi-voice VAD 录音器
===================
用 WebRTC VAD(语音活动检测)替代 ffmpeg silencedetect 的"人声自动停止"录音。

为什么:
    silencedetect 只看音量 —— 轻声说话(~-48dB)和环境噪声(~-48dB)音量重叠时
    无法区分, 阈值要么切掉轻声、要么被环境音冲破。
    WebRTC VAD 看波形特征(谐波结构), 不看音量: 轻声能识别, 电视/音乐/
    键盘声不易误触发。

用法:
    python3 vad_recorder.py /tmp/out.wav

行为:
    ffmpeg 实时采 16k 单声道 → 逐 30ms 帧喂 VAD(aggress=2)
    * 连续 3 个窗口(0.9s)内每 0.3s 都有 ≥6/10 语音帧 → 判定"开始说话",
      录音(带 0.9s 预卷, 不吞字头; 连续窗口可滤掉击键等短促噪声)
    * 说完后连续 0.8s 无语音 → 停止
    * 6s 内没人说话 → 取消(exit 2, 不转写)
    * 累计语音 <0.45s, 或录音 ≥9s 但语音占比 <40% → 疑似咳嗽/环境声,
      丢弃(exit 3, 不转写)
    * 总时长超 15s → 强制停止

退出码:
    0  录到有效语音, WAV 已写入
    2  超时未检测到语音
    3  语音不足(<0.45s 或录音≥9s但语音占比<40%, 疑似咳嗽/噪声)
    1  其他错误(ffmpeg 异常等)

依赖: webrtcvad-wheels (装在 mlx-whisper 的 pipx venv 里)
"""
import os
import shutil
import signal
import struct
import subprocess
import sys
import time
import wave

RATE = 16000
FRAME_MS = 30
FRAME_BYTES = int(RATE * FRAME_MS / 1000) * 2   # 960 字节
VAD_AGGRESS = 2

PRE_ROLL_FRAMES = 30     # 0.9s 预卷, 开始说话前的音频也保留(不吞字头)
ONSET_WIN = 10           # 触发判定的窗口(0.3s)
ONSET_THRESH = 6         # 窗口内 ≥6 帧是语音
ONSET_WINS = 3           # 连续 3 个窗口都达标才算"开始说话"(滤掉击键等短促噪声)
TAIL_MS = 800            # 说完后静音 0.8s → 停止
NO_SPEECH_TIMEOUT = 6.0  # 6s 无人说话 → 取消
MAX_SEC = 15.0           # 总时长硬上限
MIN_SPEECH_SEC = 0.45    # 累计语音 <0.45s 视为咳嗽/环境声, 丢弃
# 录音很长(≥9s)且语音占比 <40% → 环境音误报累积, 丢弃
DENSITY_MIN_FRAMES = 300
DENSITY_MIN_PCT = 40

LOG = "/tmp/pi-vad.log"


def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + msg + "\n")
    except OSError:
        pass


def write_wav(path, frames):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(frames))


def main():
    if len(sys.argv) < 2:
        print("usage: vad_recorder.py OUT.wav", file=sys.stderr)
        return 1
    out = sys.argv[1]
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    if not os.path.exists(ffmpeg):
        log("❌ ffmpeg 不存在")
        return 1

    import webrtcvad
    vad = webrtcvad.Vad(VAD_AGGRESS)
    proc = subprocess.Popen(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "avfoundation", "-i", ":0",
         "-ar", str(RATE), "-ac", "1", "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def kill(signum, frame):  # noqa: ARG001
        proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, kill)

    pre_roll = []   # 预卷帧
    win = []        # 当前窗口(10 帧)的语音标志
    good_wins = 0   # 连续达标的窗口数
    rec = []        # 录音帧(含预卷)
    started = False
    speech_total = 0   # 开始后的累计语音帧数
    tail = 0           # 连续非语音帧数
    t0 = time.time()
    buf = b""

    while True:
        chunk = proc.stdout.read(4096)
        if not chunk:
            log("❌ ffmpeg 提前退出")
            proc.wait()
            return 1
        buf += chunk
        while len(buf) >= FRAME_BYTES:
            frame = buf[:FRAME_BYTES]
            buf = buf[FRAME_BYTES:]
            is_sp = vad.is_speech(frame, RATE)
            now = time.time()

            if not started:
                pre_roll.append(frame)
                if len(pre_roll) > PRE_ROLL_FRAMES:
                    pre_roll.pop(0)
                win.append(1 if is_sp else 0)
                if len(win) == ONSET_WIN:
                    if sum(win) >= ONSET_THRESH:
                        good_wins += 1
                        if good_wins >= ONSET_WINS:
                            started = True
                            rec = list(pre_roll)
                            log("🎙 开始说话 (onset, 连续 %d 窗口)" % good_wins)
                    else:
                        good_wins = 0
                    win = []
                elif now - t0 > NO_SPEECH_TIMEOUT:
                    proc.terminate()
                    proc.wait()
                    log("6s 无语音, 取消")
                    return 2
            else:
                rec.append(frame)
                if is_sp:
                    speech_total += 1
                    tail = 0
                else:
                    tail += 1
                    if tail * FRAME_MS >= TAIL_MS:
                        proc.terminate()
                        proc.wait()
                        sp = speech_total * FRAME_MS / 1000.0
                        if sp < MIN_SPEECH_SEC or _low_density(rec, speech_total):
                            log("语音不足(%.2fs/%d帧), 丢弃" % (sp, len(rec)))
                            return 3
                        write_wav(out, rec)
                        log("✅ 写出 %s · 语音 %.2fs · 录音 %.2fs"
                            % (out, sp, len(rec) * FRAME_MS / 1000.0))
                        return 0

            if now - t0 > MAX_SEC:
                proc.terminate()
                proc.wait()
                if not started:
                    log("15s 超时且无语音")
                    return 2
                sp = speech_total * FRAME_MS / 1000.0
                if sp < MIN_SPEECH_SEC or _low_density(rec, speech_total):
                    log("语音不足(%.2fs/%d帧), 丢弃" % (sp, len(rec)))
                    return 3
                write_wav(out, rec)
                log("15s 超时强制停止 · 语音 %.2fs" % sp)
                return 0


def _low_density(rec_frames, speech_frames):
    """录音很长但语音占比过低 → 环境音误报累积, 判为无有效语音"""
    return (len(rec_frames) >= DENSITY_MIN_FRAMES
            and speech_frames * 100 < len(rec_frames) * DENSITY_MIN_PCT)


if __name__ == "__main__":
    sys.exit(main())
