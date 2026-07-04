#!/usr/bin/env python3
"""
Kokoro TTS daemon for the JARVIS hook.

Runs inside ~/.claude/jarvis/venv (needs kokoro-onnx + soundfile). Listens on
localhost and keeps the Kokoro-82M model (hexgrad/Kokoro-82M, ONNX export)
warm so replies speak near-instantly.

Model files live in ~/.claude/jarvis/models/ (kokoro-v1.0.onnx +
voices-v1.0.bin, ~340 MB total).

Endpoints:
  GET  /health -> 200 "ok" (responds even while the model is loading/speaking)
  POST /speak  -> 202; body {"text": "..."} queued for generation + playback

Behavior:
  - The model loads lazily on the first /speak (a few seconds, CPU only).
  - Text is chunked into sentence groups (~280 chars) so long replies start
    speaking sooner.
  - Requests are handled by a single worker thread, so replies play in order.
  - The daemon exits on its own after JARVIS_TTS_IDLE_EXIT seconds (default
    1800) with no requests, freeing the model's RAM.

Env vars:
  JARVIS_TTS_PORT      -> port (default 7739)
  JARVIS_TTS_IDLE_EXIT -> idle seconds before self-exit (default 1800)
  JARVIS_KOKORO_VOICE  -> voice name (default bm_george, a British male;
                          try am_michael, bm_lewis, af_heart, ...)
  JARVIS_KOKORO_SPEED  -> speech speed multiplier (default 1.0)
"""

import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("JARVIS_TTS_PORT", "7739"))
IDLE_EXIT_SECS = int(os.environ.get("JARVIS_TTS_IDLE_EXIT", "1800"))
MAX_CHUNK_CHARS = 280

_model = None
_model_lock = threading.Lock()
_last_used = time.time()
_jobs = queue.Queue()


def log(msg):
    print(f"[jarvis-ttsd] {msg}", flush=True)


MODELS_DIR = os.path.expanduser("~/.claude/jarvis/models")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jarvis_config import load_config  # noqa: E402


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            log("loading Kokoro-82M (ONNX)...")
            from kokoro_onnx import Kokoro

            _model = Kokoro(
                os.path.join(MODELS_DIR, "kokoro-v1.0.onnx"),
                os.path.join(MODELS_DIR, "voices-v1.0.bin"),
            )
            log("model ready")
        return _model


def chunk_text(text, max_chars=MAX_CHUNK_CHARS):
    """Split into sentence groups so each generation stays short."""
    sentences = re.split(r"(?<=[.!?;:])\s+", text)
    chunks, current = [], ""
    for s in sentences:
        while len(s) > max_chars:  # pathological run-on: hard split
            chunks.append(s[:max_chars])
            s = s[max_chars:]
        if len(current) + len(s) + 1 > max_chars and current:
            chunks.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        chunks.append(current)
    return chunks


def speak(text):
    import numpy as np
    import soundfile as sf

    model = get_model()
    cfg = load_config()
    voice = os.environ.get("JARVIS_KOKORO_VOICE") or cfg["voice"]
    speed = float(os.environ.get("JARVIS_KOKORO_SPEED") or cfg["speed"])

    # Generate ALL audio first, then play it as one continuous file, so
    # playback can never stall mid-reply.
    parts, sample_rate = [], None
    for chunk in chunk_text(text):
        samples, sample_rate = model.create(chunk, voice=voice, speed=speed)
        parts.append(samples)
    if not parts:
        return

    fd, path = tempfile.mkstemp(suffix=".wav", prefix="jarvis_")
    os.close(fd)
    try:
        sf.write(path, np.concatenate(parts), sample_rate)
        subprocess.run(
            ["afplay", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def worker():
    global _last_used
    while True:
        text = _jobs.get()
        try:
            speak(text)
        except Exception as e:
            log(f"speak failed: {e!r}")
        finally:
            _last_used = time.time()
            _jobs.task_done()


def idle_watchdog():
    while True:
        time.sleep(60)
        if _jobs.empty() and time.time() - _last_used > IDLE_EXIT_SECS:
            log("idle timeout, exiting")
            os._exit(0)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the log file quiet

    def _respond(self, code, body=b"ok"):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._respond(200)
        else:
            self._respond(404, b"not found")

    def do_POST(self):
        global _last_used
        if self.path != "/speak":
            self._respond(404, b"not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            text = json.loads(self.rfile.read(length)).get("text", "").strip()
        except Exception:
            self._respond(400, b"bad request")
            return
        if text:
            _last_used = time.time()
            _jobs.put(text)
        self._respond(202, b"queued")


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=idle_watchdog, daemon=True).start()
    log(f"listening on 127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
