#!/usr/bin/env python3
"""Stateless Kokoro TTS daemon.

Runs inside the JARVIS venv (kokoro-onnx, soundfile, sounddevice, scipy, numpy).
Keeps the Kokoro-82M model warm and renders on request. It holds NO voice/speed
state — those ride in each /speak request, so different sessions can use
different voices from one loaded model.

Endpoints:
  GET  /health -> 200 (responds even while loading/speaking)
  POST /speak  -> 202; body {"text","voice","speed"} queued for render + playback

Behavior:
  - One FIFO worker thread; replies play in order.
  - Playback is in-process via sounddevice, resampled to the device rate.
  - Self-exits after JARVIS_TTS_IDLE_EXIT seconds idle (default 1800).

Env: JARVIS_TTS_PORT (7739), JARVIS_TTS_IDLE_EXIT (1800).
"""

import json
import os
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DEFAULTS, MODELS_DIR  # noqa: E402
from textproc import chunk_text  # noqa: E402

PORT = int(os.environ.get("JARVIS_TTS_PORT", "7739"))
IDLE_EXIT_SECS = int(os.environ.get("JARVIS_TTS_IDLE_EXIT", "1800"))

_model = None
_model_lock = threading.Lock()
_last_used = time.time()
_jobs = queue.Queue()

_interrupt = threading.Event()      # set by /stop; checked between chunks
_stream_lock = threading.Lock()
_current_stream = None              # the OutputStream currently playing


def log(msg):
    print(f"[jarvis-ttsd] {msg}", flush=True)


def _set_current_stream(stream):
    global _current_stream
    with _stream_lock:
        _current_stream = stream


def stop_all():
    """Drain the pending queue and abort the utterance now playing."""
    while True:
        try:
            _jobs.get_nowait()
            _jobs.task_done()
        except queue.Empty:
            break
    _interrupt.set()
    with _stream_lock:
        if _current_stream is not None:
            try:
                _current_stream.abort()
            except Exception:
                pass


def configure_threads():
    """Tune onnxruntime CPU threads before the model loads. onnxruntime honors
    OMP_NUM_THREADS; default to the core count instead of the library default."""
    n = os.environ.get("JARVIS_TTS_THREADS") or str(os.cpu_count() or 1)
    os.environ.setdefault("OMP_NUM_THREADS", n)


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            configure_threads()
            log("loading Kokoro-82M (ONNX)...")
            from kokoro_onnx import Kokoro

            _model = Kokoro(
                os.path.join(MODELS_DIR, "kokoro-v1.0.onnx"),
                os.path.join(MODELS_DIR, "voices-v1.0.bin"),
            )
            log("model ready")
        return _model


def warmup():
    """Load the model and warm the ONNX graph with a throwaway utterance."""
    try:
        model = get_model()
        model.create(".", voice=DEFAULTS["voice"], speed=1.0)
        log("warmup complete")
    except Exception as e:
        log(f"warmup failed: {e!r}")


def render_and_play(text, voice, speed):
    """Producer/consumer streaming: synthesize chunk N+1 while chunk N plays, so
    the first audio lands after one sentence instead of the whole reply."""
    import audio

    _interrupt.clear()
    model = get_model()
    dst = audio.device_rate()
    chunks = chunk_text(text)
    if not chunks:
        return

    rendered = queue.Queue(maxsize=4)

    def produce():
        try:
            for chunk in chunks:
                if _interrupt.is_set():
                    break
                samples, sr = model.create(chunk, voice=voice, speed=speed)
                rendered.put(audio.resample(samples, sr, dst))
        except Exception as e:
            log(f"synth failed: {e!r}")
        finally:
            rendered.put(None)  # sentinel

    threading.Thread(target=produce, daemon=True).start()

    stream = audio.open_output_stream(dst)
    _set_current_stream(stream)
    try:
        while not _interrupt.is_set():
            wave = rendered.get()
            if wave is None:
                break
            try:
                stream.write(wave)
            except Exception:
                break  # aborted by /stop
    finally:
        _set_current_stream(None)
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass


def worker():
    global _last_used
    while True:
        job = _jobs.get()
        try:
            render_and_play(job["text"], job["voice"], job["speed"])
        except Exception as e:
            log(f"render failed: {e!r}")
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
        pass

    def _respond(self, code, body=b"ok"):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._respond(200)
        elif self.path == "/warmup":
            threading.Thread(target=warmup, daemon=True).start()
            self._respond(202, b"warming")
        else:
            self._respond(404, b"not found")

    def do_POST(self):
        global _last_used
        if self.path == "/warmup":
            threading.Thread(target=warmup, daemon=True).start()
            self._respond(202, b"warming")
            return
        if self.path == "/stop":
            stop_all()
            self._respond(200, b"stopped")
            return
        if self.path != "/speak":
            self._respond(404, b"not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            text = (body.get("text") or "").strip()
        except Exception:
            self._respond(400, b"bad request")
            return
        if text:
            _last_used = time.time()
            _jobs.put({
                "text": text,
                "voice": body.get("voice") or DEFAULTS["voice"],
                "speed": float(body.get("speed") or DEFAULTS["speed"]),
            })
        self._respond(202, b"queued")


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=idle_watchdog, daemon=True).start()
    threading.Thread(target=warmup, daemon=True).start()  # warm at boot, non-blocking
    log(f"listening on 127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
