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
from config import ARMED_DIR, DEFAULTS, JARVIS_HOME, MODELS_DIR, SESSIONS_DIR, load_config  # noqa: E402
from textproc import chunk_text  # noqa: E402

PORT = int(os.environ.get("JARVIS_TTS_PORT", "7739"))
IDLE_EXIT_SECS = int(os.environ.get("JARVIS_TTS_IDLE_EXIT", "1800"))
DEVICE_RETRY_SECS = 0.5

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


def _open_fresh_stream():
    """Device rate + output stream against a freshly enumerated device list."""
    import audio

    audio.reset()
    dst = audio.device_rate()
    return dst, audio.open_output_stream(dst)


def speak_system_fallback(job):
    """Last-resort per-OS system TTS, so a dead audio device never means
    silence (the system voice keeps working across device changes)."""
    import fallback

    try:
        fallback.speak(job["text"], load_config(job["session"]).get("say_voice"))
        event("fallback", session=job["session"], chars=len(job["text"]))
    except Exception as e:
        log(f"system fallback failed: {e!r}")


def render_and_play(job):
    """Producer/consumer streaming: synthesize chunk N+1 while chunk N plays, so
    the first audio lands after one sentence instead of the whole reply."""
    import audio

    abort = job["abort"]
    model = get_model()
    chunks = chunk_text(job["text"])
    if not chunks or abort.is_set():
        return  # stopped while we were setting up: don't touch the device

    # The output device can change or vanish between jobs (AirPods, USB
    # audio, display speakers); open against a fresh device list, retry once,
    # and drop to the system TTS rather than staying silent.
    try:
        dst, stream = _open_fresh_stream()
    except Exception as e:
        event("device_error", session=job["session"], error=repr(e))
        log(f"output device unavailable, retrying: {e!r}")
        time.sleep(DEVICE_RETRY_SECS)
        if abort.is_set():
            return
        try:
            dst, stream = _open_fresh_stream()
        except Exception as e:
            event("device_error", session=job["session"], error=repr(e))
            log(f"output device still unavailable, using system TTS: {e!r}")
            speak_system_fallback(job)
            return

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

    event("play_start", session=job["session"], chars=len(job["text"]))
    started = time.time()
    _set_current_stream(stream)
    try:
        while not abort.is_set():
            wave = rendered.get()
            if wave is None:
                break
            try:
                stream.write(wave)
            except Exception as e:
                if not abort.is_set():  # /stop aborts the stream; that's not an error
                    event("play_error", session=job["session"], error=repr(e))
                    log(f"playback failed mid-stream: {e!r}")
                break
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
<title>JARVIS voice — status</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         background:#0d1117; color:#c9d4e0; margin:0; padding:24px; max-width:1080px; }
  a { color:#6db3f2; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  header { display:flex; align-items:center; gap:12px; margin-bottom:4px; }
  header h1 { font-size:19px; font-weight:600; margin:0; color:#e8eef5; flex:0 0 auto; }
  .pill { display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:600;
          padding:3px 10px; border-radius:999px; }
  .pill .dot { width:8px; height:8px; border-radius:50%; background:currentColor; }
  .pill.online { color:#3fbf6f; background:#123020; }
  .pill.offline { color:#e05555; background:#301616; }
  .spacer { flex:1; }
  .btn { background:#1e2630; color:#c9d4e0; border:1px solid #2c3745;
         border-radius:6px; padding:5px 12px; cursor:pointer; font:inherit; font-size:13px; }
  .btn:hover { background:#2c3745; }
  .btn.danger { color:#f0a0a0; border-color:#4a2626; }
  .btn.danger:hover { background:#3a1c1c; }
  .btn.sm { padding:2px 9px; font-size:12px; }
  .sub { color:#6f7d8c; font-size:12.5px; margin:0 0 18px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
           gap:10px; margin-bottom:18px; }
  .card { background:#151b23; border:1px solid #1e2630; border-radius:8px; padding:11px 13px; }
  .card .label { color:#6f7d8c; font-size:11px; text-transform:uppercase; letter-spacing:.06em; }
  .card .value { font-size:17px; font-weight:600; color:#e8eef5; margin-top:3px; }
  .card .value.good { color:#3fbf6f; } .card .value.warn { color:#d9a441; }
  .card .value.muted { color:#7f8ea0; }
  .now { display:flex; align-items:center; gap:12px; background:#122335;
         border:1px solid #244b6e; border-radius:8px; padding:12px 14px; margin-bottom:18px; }
  .now.idle { background:#151b23; border-color:#1e2630; color:#6f7d8c; }
  .now .eq { font-size:20px; }
  .now .who { color:#9dc7f5; font-weight:600; }
  .now .say { color:#c9d4e0; flex:1; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:0 28px; }
  @media (max-width:820px){ .grid { grid-template-columns:1fr; } }
  h2 { font-size:12px; text-transform:uppercase; letter-spacing:.07em;
       color:#7f8ea0; margin:20px 0 8px; font-weight:600; }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  td, th { padding:5px 10px 5px 0; text-align:left; vertical-align:top;
           border-bottom:1px solid #1a222c; }
  th { color:#6f7d8c; font-weight:500; font-size:11px; text-transform:uppercase; letter-spacing:.05em; }
  tr:last-child td { border-bottom:none; }
  .sid { color:#6db3f2; }
  .txt { color:#8b98a6; }
  .empty { color:#5a6673; font-style:italic; }
  .badge { display:inline-block; font-size:11px; font-weight:600; padding:1px 7px; border-radius:5px; }
  .badge.on { color:#3fbf6f; background:#123020; }
  .badge.once { color:#d9a441; background:#2e2410; }
  .badge.off { color:#7f8ea0; background:#1c232c; }
  .ev { display:flex; gap:8px; align-items:baseline; padding:5px 0; border-bottom:1px solid #1a222c; }
  .ev:last-child { border-bottom:none; }
  .ev .ico { flex:0 0 auto; width:18px; text-align:center; }
  .ev .msg { flex:1; }
  .ev .when { color:#5a6673; font-size:11.5px; flex:0 0 auto; }
  .ev.err .msg { color:#e88; }
  .ev.good .msg { color:#7fc99a; }
  details { margin-top:10px; }
  summary { cursor:pointer; color:#7f8ea0; font-size:12px; text-transform:uppercase;
            letter-spacing:.07em; font-weight:600; }
  pre { background:#0a0e13; border:1px solid #1a222c; border-radius:6px; margin-top:8px;
        padding:10px; overflow:auto; max-height:280px; white-space:pre-wrap;
        font: 12px/1.5 ui-monospace, Menlo, monospace; color:#93a1af; }
</style>
<header>
  <h1>JARVIS voice</h1>
  <span id="pill" class="pill offline"><span class="dot"></span><span id="pilltxt">connecting…</span></span>
  <span class="spacer"></span>
  <button class="btn danger" id="stopall">⏹ Stop all speech</button>
</header>
<p class="sub" id="sub">Local text-to-speech daemon. This page refreshes every 2 seconds.</p>

<div class="cards" id="cards"></div>
<div class="now idle" id="now">Idle — nothing is playing right now.</div>

<div class="grid">
  <div>
    <h2>Sessions</h2>
    <table id="sessions"></table>
    <h2>Waiting to be spoken</h2>
    <table id="queue"></table>
  </div>
  <div>
    <h2>Recent activity</h2>
    <div id="events"></div>
  </div>
</div>

<details>
  <summary>Logs</summary>
  <h2>hook.log <span class="txt">— the Stop hook that decides what to speak</span></h2>
  <pre id="hooklog"></pre>
  <h2>daemon.log <span class="txt">— this speech engine's own output</span></h2>
  <pre id="daemonlog"></pre>
</details>

<script>
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const sid = s => s ? esc(String(s).slice(0, 8)) : "—";
const dur = sec => sec < 60 ? sec+"s" : Math.floor(sec/60)+"m "+(sec%60)+"s";
function ago(t){
  const d = Date.now()/1000 - t;
  if (d < 2) return "just now";
  if (d < 60) return Math.floor(d)+"s ago";
  if (d < 3600) return Math.floor(d/60)+"m ago";
  return Math.floor(d/3600)+"h ago";
}

// kind -> [icon, human label, css class]
const EV = {
  queued:      ["📥", "Queued for speech", ""],
  play_start:  ["▶️", "Started speaking", "good"],
  play_done:   ["✅", "Finished speaking", "good"],
  superseded:  ["⏭️", "Replaced by a newer reply", ""],
  stop:        ["⏹️", "Speech stopped", ""],
  warmup:      ["🔥", "Voice model warmed up", "good"],
  fallback:    ["🗣️", "Used the system voice (Kokoro unavailable)", "err"],
  synth_error: ["⚠️", "Could not generate audio", "err"],
  device_error:["🔌", "Audio device problem", "err"],
  play_error:  ["⚠️", "Playback failed", "err"],
  sweep:       ["🧹", "Cleaned up old sessions", ""],
};
function evDetail(e){
  if (e.error) return esc(e.error);
  if (e.kind === "play_done" && e.secs != null) return "took " + e.secs + "s";
  if (e.removed != null) return e.removed + " removed";
  if (e.text) return '"' + esc(e.text) + '"';
  if (e.chars != null) return e.chars + " characters";
  return "";
}

function stop(body){ return fetch("/stop", {method:"POST", body}).then(() => setTimeout(tick, 150)); }
document.getElementById("stopall").onclick = () => stop("{}");
document.addEventListener("click", e => {
  const b = e.target.closest("[data-stop]");
  if (b) stop(JSON.stringify({session_id: b.getAttribute("data-stop")}));
});

// Replace log text only when it changed, and keep it pinned to the bottom,
// so the panel doesn't reset your scroll position on every refresh.
function setLog(id, lines){
  const el = document.getElementById(id);
  const txt = lines.length ? lines.join("\\n") : "(nothing logged yet)";
  if (el.textContent === txt) return;
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
  el.textContent = txt;
  if (atBottom) el.scrollTop = el.scrollHeight;
}

function offline(){
  document.getElementById("pill").className = "pill offline";
  document.getElementById("pilltxt").textContent = "daemon offline";
}

async function tick(){
  let s;
  try { s = await (await fetch("/status")).json(); }
  catch(e){ offline(); return; }

  document.getElementById("pill").className = "pill online";
  document.getElementById("pilltxt").textContent = "online";

  const card = (label, value, cls) =>
    `<div class="card"><div class="label">${label}</div><div class="value ${cls||''}">${value}</div></div>`;
  document.getElementById("cards").innerHTML =
    card("Voice model", s.warmed ? "Ready" : "Loading…", s.warmed ? "good" : "warn") +
    card("Right now", s.speaking ? "Speaking" : "Idle", s.speaking ? "good" : "muted") +
    card("Waiting", s.queue.length, s.queue.length ? "warn" : "muted") +
    card("Uptime", dur(s.uptime_secs)) +
    card("Process", '<span class="mono">' + s.pid + " · :" + s.port + "</span>", "muted");

  const now = document.getElementById("now");
  if (s.current){
    now.className = "now";
    now.innerHTML =
      `<span class="eq">🔊</span>
       <span><span class="who">${sid(s.current.session)}</span>
       <div class="say">"${esc(s.current.text)}"</div></span>
       <button class="btn sm danger" data-stop="${esc(s.current.session)}">stop</button>`;
  } else {
    now.className = "now idle";
    now.textContent = "Idle — nothing is playing right now.";
  }

  document.getElementById("sessions").innerHTML =
    `<tr><th>Session</th><th>Voice</th><th>Idle for</th><th>Custom settings</th><th></th></tr>` +
    (s.sessions.map(x => {
      const b = x.armed === "on" ? '<span class="badge on">armed</span>'
              : x.armed === "once" ? '<span class="badge once">armed once</span>'
              : '<span class="badge off">off</span>';
      return `<tr><td class="sid mono">${sid(x.session)}</td><td>${b}</td>
        <td class="txt">${x.age_secs != null ? Math.floor(x.age_secs/60)+"m" : "—"}</td>
        <td class="txt">${x.override && Object.keys(x.override).length ? esc(JSON.stringify(x.override)) : "—"}</td>
        <td><button class="btn sm" data-stop="${esc(x.session)}">stop</button></td></tr>`;
    }).join("") || `<tr><td colspan="5" class="empty">No sessions have used the voice yet.</td></tr>`);

  document.getElementById("queue").innerHTML = s.queue.length
    ? `<tr><th>Session</th><th>Length</th><th>Preview</th></tr>` + s.queue.map(q =>
        `<tr><td class="sid mono">${sid(q.session)}</td><td class="txt">${q.chars} chars</td>
         <td class="txt">"${esc(q.text)}"</td></tr>`).join("")
    : `<tr><td class="empty">Nothing waiting.</td></tr>`;

  document.getElementById("events").innerHTML = s.events.length
    ? s.events.slice().reverse().map(e => {
        const [ico, label, cls] = EV[e.kind] || ["•", e.kind, ""];
        const who = e.session ? ' <span class="sid mono">' + sid(e.session) + '</span>' : "";
        const det = evDetail(e);
        return `<div class="ev ${cls}"><span class="ico">${ico}</span>
          <span class="msg">${esc(label)}${who}${det ? ' — <span class="txt">'+det+'</span>' : ''}</span>
          <span class="when">${ago(e.t)}</span></div>`;
      }).join("")
    : `<div class="empty">No activity yet.</div>`;

  setLog("hooklog", s.logs.hook);
  setLog("daemonlog", s.logs.daemon);
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
