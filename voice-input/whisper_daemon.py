#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pi-voice-input Whisper 常驻转写守护进程
=======================================
常驻加载一次模型(whisper-large-v3-turbo)，通过本地 HTTP 服务循环转写，
避免每次调用重新加载模型(~2.8s)以及 HF Hub 网络检查抖动(可随机卡 30s+)。

协议 (127.0.0.1:18765):
  GET  /health      -> {"status": "ok"}                模型已就绪
  POST /transcribe  -> {"text": "..."}
        body: {"audio": "/path/to.wav", "language": "zh" | null}

日志: /tmp/pi-whisper-daemon.log
PID : /tmp/pi-whisper-daemon.pid

停止: kill $(cat /tmp/pi-whisper-daemon.pid)
"""
import json
import os
import sys
import time
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 保证 ffmpeg 可用（mlx_whisper 内部用 ffmpeg 解码音频）
os.environ["PATH"] = os.pathsep.join([
    "/opt/homebrew/bin",
    str(Path.home() / ".local/bin"),
    os.environ.get("PATH", ""),
])

PORT = int(os.environ.get("PI_WHISPER_PORT", "18765"))
MODEL_REPO = os.environ.get("PI_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
PID_FILE = "/tmp/pi-whisper-daemon.pid"
LOG_FILE = "/tmp/pi-whisper-daemon.log"

# 屏蔽 tqdm 进度条输出（否则会刷进日志文件）
os.environ["TQDM_DISABLE"] = "1"

# mlx_whisper 显式传 disable=verbose is not False, 不理会 TQDM_DISABLE;
# 用 no-op 桩替换 tqdm.tqdm, 彻底去掉进度条, 同时规避 stderr/BrokenPipe 隐患
class _NullBar:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def update(self, *a, **k):
        pass

    def close(self):
        pass

import tqdm as _tqdm
_tqdm.tqdm = lambda *a, **k: _NullBar()

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("whisper-daemon")

_lock = threading.Lock()
_model_path = None
_transcribe = None


def resolve_model_path() -> str:
    """优先用本地 HF 缓存快照(零网络)，没有缓存才联网下载一次(首次安装)。"""
    cache_dir = (
        Path.home()
        / ".cache/huggingface/hub"
        / ("models--" + MODEL_REPO.replace("/", "--"))
    )
    candidates = []
    ref_file = cache_dir / "refs" / "main"
    if ref_file.exists():
        rev = ref_file.read_text().strip()
        candidates.append(cache_dir / "snapshots" / rev)
    snap_dir = cache_dir / "snapshots"
    if snap_dir.exists():
        candidates += sorted(snap_dir.iterdir())
    for cand in candidates:
        if (cand / "weights.safetensors").exists():
            log.info("使用本地缓存模型: %s", cand)
            return str(cand)
    from huggingface_hub import snapshot_download
    log.info("本地无模型缓存，开始联网下载…")
    return snapshot_download(MODEL_REPO)


def load() -> None:
    global _model_path, _transcribe
    from mlx_whisper.transcribe import ModelHolder
    import mlx.core as mx
    import mlx_whisper

    _model_path = resolve_model_path()
    t0 = time.time()
    ModelHolder.get_model(_model_path, mx.float16)  # 预加载，与 transcribe 默认 dtype 一致
    log.info("模型加载完成: %.1fs", time.time() - t0)
    _transcribe = mlx_whisper.transcribe


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 屏蔽默认访问日志
        pass

    def _send(self, code: int, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/transcribe"):
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            audio = body.get("audio")
            language = body.get("language") or None
            if not audio or not os.path.isfile(audio):
                self._send(400, {"error": "audio 文件不存在: %s" % audio})
                return
            with _lock:  # 串行转写，避免并发争用模型
                t0 = time.time()
                kwargs = {"audio": audio, "path_or_hf_repo": _model_path, "verbose": False}
                if language:
                    kwargs["language"] = language
                result = _transcribe(**kwargs)
                text = (result.get("text") or "").strip()
                log.info("转写 %s 用时 %.2fs, %d 字", Path(audio).name, time.time() - t0, len(text))
                self._send(200, {"text": text})
        except json.JSONDecodeError:
            self._send(400, {"error": "请求体不是合法 JSON"})
        except Exception as e:  # noqa: BLE001
            log.exception("转写失败")
            self._send(500, {"error": str(e)})


def main():
    # 后台运行时 stderr 管道可能被关闭，重定向到日志避免 BrokenPipeError
    try:
        sys.stderr = open(LOG_FILE, "a")
    except OSError:
        pass
    # 已有活进程则退出（防重复启动）
    if os.path.exists(PID_FILE):
        try:
            old = int(Path(PID_FILE).read_text().strip())
            os.kill(old, 0)
            log.info("已有运行中的守护进程 PID=%d，退出", old)
            sys.exit(0)
        except (ValueError, ProcessLookupError):
            pass
    Path(PID_FILE).write_text(str(os.getpid()))

    log.info("启动 PID=%d PORT=%d", os.getpid(), PORT)
    load()
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        log.error("端口 %d 被占用: %s", PORT, e)
        sys.exit(1)
    log.info("就绪: http://127.0.0.1:%d (模型已热)", PORT)
    srv.serve_forever()


if __name__ == "__main__":
    main()
