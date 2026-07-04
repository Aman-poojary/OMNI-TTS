#!/usr/bin/env python3
"""Stateless Kokoro TTS daemon.

Runs inside the JARVIS venv (kokoro-onnx, soundfile, sounddevice, scipy, numpy).
Keeps the Kokoro-82M model warm and renders on request. It holds NO voice/speed
state — those ride in each /speak request, so different sessions can use
different voices from one loaded model.

Endpoints:
  GET  /health -> 200 (responds even while loading/speaking)
  GET  /status -> JSON: warmed, current job, queue, recent events, sessions, logs
  GET  /ui     -> self-contained debug page rendering /status
  POST /speak  -> 202; {"text","voice","speed","session_id"} queued for playback
  POST /stop   -> stop playback; {"session_id"} scopes it to one session,
                  empty body stops everything
  POST /disarm -> {"session_id"} stop that session's audio and delete its
                  arming flag + override files (same as /jarvis-off)
  POST /warmup -> load + warm the model (blocking)

Behavior:
  - One FIFO worker thread; replies play in order across sessions.
  - A new /speak for a session supersedes that session's queued (unplayed) jobs,
    so back-to-back replies never pile up behind each other.
  - Playback is in-process via sounddevice, resampled to the device rate.
  - Self-exits after JARVIS_TTS_IDLE_EXIT seconds idle (default 1800).

Env: JARVIS_TTS_PORT (7739), JARVIS_TTS_IDLE_EXIT (1800).
"""

import collections
import json
import os
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import ARMED_DIR, DEFAULTS, JARVIS_HOME, MODELS_DIR, SESSIONS_DIR  # noqa: E402
from textproc import chunk_text  # noqa: E402

PORT = int(os.environ.get("JARVIS_TTS_PORT", "7739"))
IDLE_EXIT_SECS = int(os.environ.get("JARVIS_TTS_IDLE_EXIT", "1800"))

_model = None
_model_lock = threading.Lock()
_warmup_lock = threading.Lock()
_warmed = False
_started = time.time()
_last_used = time.time()

# Pending jobs live in a scannable deque (not a Queue) so /stop and supersede
# can remove one session's jobs without disturbing the others.
_cond = threading.Condition()
_pending = collections.deque()
_current_job = None
_job_seq = 0

_stream_lock = threading.Lock()
_current_stream = None              # the OutputStream currently playing

_events = collections.deque(maxlen=200)


def log(msg):
    print(f"[jarvis-ttsd] {msg}", flush=True)


def event(kind, **fields):
    fields["t"] = time.time()
    fields["kind"] = kind
    _events.append(fields)


def _snippet(text, n=100):
    return text[:n] + ("…" if len(text) > n else "")


def _set_current_stream(stream):
    global _current_stream
    with _stream_lock:
        _current_stream = stream


def _abort_current_stream():
    with _stream_lock:
        if _current_stream is not None:
            try:
                _current_stream.abort()
            except Exception:
                pass


def enqueue(text, voice, speed, session_id):
    """Queue a job; a newer reply supersedes the session's unplayed ones."""
    global _job_seq
    with _cond:
        if session_id:
            stale = [j for j in _pending if j["session"] == session_id]
            for j in stale:
                j["abort"].set()
                _pending.remove(j)
                event("superseded", session=session_id, text=_snippet(j["text"]))
        _job_seq += 1
        job = {
            "id": _job_seq,
            "text": text,
            "voice": voice,
            "speed": speed,
            "session": session_id or "",
            "abort": threading.Event(),
            "queued_at": time.time(),
        }
        _pending.append(job)
        event("queued", session=job["session"], chars=len(text), text=_snippet(text))
        _cond.notify()


def stop_jobs(session_id=None):
    """Abort queued + playing jobs. Scoped to one session when given, else all."""
    with _cond:
        for j in list(_pending):
            if session_id and j["session"] != session_id:
                continue
            j["abort"].set()
            _pending.remove(j)
        cur = _current_job
        if cur is not None and (not session_id or cur["session"] == session_id):
            cur["abort"].set()
            _abort_current_stream()
    event("stop", session=session_id or "(all)")


def _next_job():
    global _current_job
    with _cond:
        while not _pending:
            _cond.wait()
        _current_job = _pending.popleft()
        return _current_job


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
    global _warmed
    try:
        with _warmup_lock:
            if _warmed:
                return
            model = get_model()
            model.create(".", voice=DEFAULTS["voice"], speed=1.0)
            _warmed = True
        event("warmup")
        log("warmup complete")
    except Exception as e:
        log(f"warmup failed: {e!r}")


def _put_sentinel(q):
    """Guarantee the None sentinel lands even if the queue is full (consumer
    gone): drop a rendered chunk to make room rather than block forever."""
    while True:
        try:
            q.put_nowait(None)
            return
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass


def render_and_play(job):
    """Producer/consumer streaming: synthesize chunk N+1 while chunk N plays, so
    the first audio lands after one sentence instead of the whole reply."""
    import audio

    abort = job["abort"]
    model = get_model()
    dst = audio.device_rate()
    chunks = chunk_text(job["text"])
    if not chunks or abort.is_set():
        return  # stopped while we were setting up: don't touch the device

    rendered = queue.Queue(maxsize=4)

    def produce():
        try:
            for chunk in chunks:
                if abort.is_set():
                    break
                samples, sr = model.create(chunk, voice=job["voice"], speed=job["speed"])
                if abort.is_set():
                    break
                wave = audio.resample(samples, sr, dst)
                while not abort.is_set():
                    try:
                        rendered.put(wave, timeout=0.1)
                        break
                    except queue.Full:
                        pass
        except Exception as e:
            event("synth_error", session=job["session"], error=repr(e))
            log(f"synth failed: {e!r}")
        finally:
            _put_sentinel(rendered)

    threading.Thread(target=produce, daemon=True).start()

    if abort.is_set():
        return
    event("play_start", session=job["session"], chars=len(job["text"]))
    started = time.time()
    stream = audio.open_output_stream(dst)
    _set_current_stream(stream)
    try:
        while not abort.is_set():
            wave = rendered.get()
            if wave is None:
                break
            try:
                stream.write(wave)
            except Exception:
                break  # aborted by /stop or device error
    finally:
        # Unblock the producer no matter how we exited (stop, device error),
        # so it never spins on a queue nobody drains.
        abort.set()
        _set_current_stream(None)
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        event("play_done", session=job["session"],
              secs=round(time.time() - started, 1))


def worker():
    global _last_used, _current_job
    while True:
        job = _next_job()
        try:
            render_and_play(job)
        except Exception as e:
            log(f"render failed: {e!r}")
        finally:
            with _cond:
                _current_job = None
            _last_used = time.time()


def idle_watchdog():
    import cleanup

    while True:
        time.sleep(60)
        removed = cleanup.sweep()  # age-based backstop for Codex / crashed sessions
        if removed:
            event("sweep", removed=removed)
        with _cond:
            busy = bool(_pending) or _current_job is not None
        if not busy and time.time() - _last_used > IDLE_EXIT_SECS:
            log("idle timeout, exiting")
            os._exit(0)


def _list_sessions():
    """Session state on disk: arming flags + per-session overrides."""
    sessions = {}
    try:
        for name in os.listdir(ARMED_DIR):
            if name.startswith("."):
                continue  # .pending intent marker, not a session
            sid = name[:-5] if name.endswith(".once") else name
            entry = sessions.setdefault(sid, {"armed": "", "override": None})
            mode = "once" if name.endswith(".once") else "on"
            entry["armed"] = mode if not entry["armed"] else "on"
            entry["age_secs"] = int(time.time() - os.path.getmtime(os.path.join(ARMED_DIR, name)))
    except OSError:
        pass
    try:
        for name in os.listdir(SESSIONS_DIR):
            if not name.endswith(".json"):
                continue
            sid = name[:-5]
            entry = sessions.setdefault(sid, {"armed": "", "override": None})
            try:
                with open(os.path.join(SESSIONS_DIR, name), encoding="utf-8") as f:
                    entry["override"] = json.load(f)
            except Exception:
                entry["override"] = {}
    except OSError:
        pass
    return [{"session": sid, **info} for sid, info in sorted(sessions.items())]


def _tail(path, max_bytes=6000):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="ignore").splitlines()[-40:]
    except OSError:
        return []


def status_payload():
    with _cond:
        cur = _current_job
        current = None
        if cur is not None:
            current = {"session": cur["session"], "chars": len(cur["text"]),
                       "text": _snippet(cur["text"])}
        pending = [{"session": j["session"], "chars": len(j["text"]),
                    "text": _snippet(j["text"])} for j in _pending]
    return {
        "pid": os.getpid(),
        "port": PORT,
        "warmed": _warmed,
        "uptime_secs": int(time.time() - _started),
        "speaking": current is not None,
        "current": current,
        "queue": pending,
        "events": list(_events)[-60:],
        "sessions": _list_sessions(),
        "logs": {
            "hook": _tail(os.path.join(JARVIS_HOME, "hook.log")),
            "daemon": _tail(os.path.join(JARVIS_HOME, "daemon.log")),
        },
    }


UI_HTML = """<!doctype html>
<meta charset="utf-8">
<title>JARVIS debug</title>
<style>
  :root { color-scheme: dark; }
  body { font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
         background:#101418; color:#cdd6e0; margin:0; padding:20px; }
  h1 { font-size:16px; margin:0 0 4px; color:#e8eef5; }
  h1 .dot { display:inline-block; width:10px; height:10px; border-radius:50%;
            background:#e05555; margin-right:8px; }
  h1 .dot.ok { background:#3fbf6f; }
  h2 { font-size:12px; text-transform:uppercase; letter-spacing:.08em;
       color:#7f8ea0; margin:22px 0 6px; }
  .meta { color:#7f8ea0; margin-bottom:10px; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:0 28px; }
  @media (max-width:900px){ .grid { grid-template-columns:1fr; } }
  table { border-collapse:collapse; width:100%; }
  td, th { padding:3px 10px 3px 0; text-align:left; vertical-align:top;
           border-bottom:1px solid #1e2630; }
  th { color:#7f8ea0; font-weight:normal; }
  .sid { color:#6db3f2; }
  .txt { color:#9aa7b5; }
  .kind { color:#d9a441; }
  .kind.play_start, .kind.play_done { color:#3fbf6f; }
  .kind.stop, .kind.superseded, .kind.synth_error, .kind.disarm { color:#e05555; }
  pre { background:#0b0f13; border:1px solid #1e2630; border-radius:6px;
        padding:10px; overflow-x:auto; max-height:260px; overflow-y:auto;
        white-space:pre-wrap; }
  button { background:#1e2630; color:#cdd6e0; border:1px solid #2c3745;
           border-radius:5px; padding:2px 10px; cursor:pointer; font:inherit; }
  button:hover { background:#2c3745; }
  .now { background:#13202e; border:1px solid #204060; border-radius:6px;
         padding:8px 12px; margin:6px 0; }
</style>
<h1><span id="dot" class="dot"></span>JARVIS TTS daemon <button onclick="stopAll()" style="float:right">⏹ stop all</button></h1>
<div class="meta" id="meta">connecting…</div>
<div id="now"></div>
<div class="grid">
  <div>
    <h2>Sessions</h2>
    <table id="sessions"></table>
    <h2>Queue</h2>
    <table id="queue"></table>
    <h2>Events</h2>
    <table id="events"></table>
  </div>
  <div>
    <h2>hook.log</h2><pre id="hooklog"></pre>
    <h2>daemon.log</h2><pre id="daemonlog"></pre>
  </div>
</div>
<script>
const esc = s => String(s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const short = s => esc(String(s).slice(0, 12));
const hhmmss = t => new Date(t * 1000).toLocaleTimeString();
function stopAll(){ fetch("/stop", {method:"POST", body:"{}"}); }
function stopSession(sid){ fetch("/stop", {method:"POST", body: JSON.stringify({session_id: sid})}); }
function disarmSession(sid){ fetch("/disarm", {method:"POST", body: JSON.stringify({session_id: sid})}).then(tick); }
async function tick(){
  let s;
  try { s = await (await fetch("/status")).json(); }
  catch(e){ document.getElementById("meta").textContent = "daemon unreachable";
            document.getElementById("dot").className = "dot"; return; }
  document.getElementById("dot").className = "dot ok";
  document.getElementById("meta").textContent =
    `pid ${s.pid} · port ${s.port} · ${s.warmed ? "model warm" : "model cold"}` +
    ` · up ${Math.floor(s.uptime_secs/60)}m · queue ${s.queue.length}`;
  document.getElementById("now").innerHTML = s.current
    ? `<div class="now">▶ speaking <span class="sid">${short(s.current.session)}</span>
       (${s.current.chars} ch) <span class="txt">${esc(s.current.text)}</span>
       <button onclick="stopSession('${esc(s.current.session)}')">stop</button></div>` : "";
  document.getElementById("sessions").innerHTML =
    `<tr><th>session</th><th>armed</th><th>age</th><th>override</th><th></th></tr>` +
    (s.sessions.map(x => `<tr><td class="sid">${short(x.session)}</td>
      <td>${esc(x.armed || "—")}</td><td>${x.age_secs != null ? Math.floor(x.age_secs/60)+"m" : ""}</td>
      <td class="txt">${x.override ? esc(JSON.stringify(x.override)) : ""}</td>
      <td><button onclick="stopSession('${esc(x.session)}')">stop</button>
          <button onclick="disarmSession('${esc(x.session)}')">disarm</button></td></tr>`).join("")
     || `<tr><td class="txt">no session state on disk</td></tr>`);
  document.getElementById("queue").innerHTML = s.queue.length
    ? s.queue.map(q => `<tr><td class="sid">${short(q.session)}</td>
        <td>${q.chars} ch</td><td class="txt">${esc(q.text)}</td></tr>`).join("")
    : `<tr><td class="txt">empty</td></tr>`;
  document.getElementById("events").innerHTML = s.events.slice().reverse().map(e =>
    `<tr><td>${hhmmss(e.t)}</td><td class="kind ${esc(e.kind)}">${esc(e.kind)}</td>
     <td class="sid">${short(e.session || "")}</td>
     <td class="txt">${esc(e.text || e.error || (e.secs != null ? e.secs+"s" : "") || (e.removed != null ? e.removed+" removed" : ""))}</td></tr>`).join("");
  document.getElementById("hooklog").textContent = s.logs.hook.join("\\n");
  document.getElementById("daemonlog").textContent = s.logs.daemon.join("\\n");
}
tick(); setInterval(tick, 2000);
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _respond(self, code, body=b"ok", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._respond(200)
        elif self.path == "/status":
            body = json.dumps(status_payload()).encode("utf-8")
            self._respond(200, body, "application/json")
        elif self.path in ("/ui", "/"):
            self._respond(200, UI_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/warmup":
            warmup()
            self._respond(200, b"warm")
        else:
            self._respond(404, b"not found")

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            return None

    def do_POST(self):
        global _last_used
        if self.path == "/warmup":
            warmup()
            self._respond(200, b"warm")
            return
        if self.path == "/stop":
            body = self._read_body() or {}
            stop_jobs(body.get("session_id") or None)
            self._respond(200, b"stopped")
            return
        if self.path == "/disarm":
            body = self._read_body() or {}
            sid = body.get("session_id")
            if not sid:
                self._respond(400, b"session_id required")
                return
            import cleanup

            stop_jobs(sid)
            cleanup.cleanup_session(sid)
            event("disarm", session=sid)
            self._respond(200, b"disarmed")
            return
        if self.path != "/speak":
            self._respond(404, b"not found")
            return
        body = self._read_body()
        if body is None:
            self._respond(400, b"bad request")
            return
        text = (body.get("text") or "").strip()
        if text:
            _last_used = time.time()
            enqueue(
                text,
                body.get("voice") or DEFAULTS["voice"],
                float(body.get("speed") or DEFAULTS["speed"]),
                body.get("session_id") or "",
            )
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
