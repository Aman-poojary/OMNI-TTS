#!/usr/bin/env python3
"""Client for the JARVIS TTS daemon. Stdlib-only, runs under any python3.

Called detached by speak.py as: ``tts_client.py <text> [session_id]``. Loads the
session's effective config, ensures the daemon is up (starting it from the venv
if needed), and POSTs ``{text, voice, speed}``. Falls back to system TTS if the
daemon can't be reached.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import JARVIS_HOME, load_config  # noqa: E402

PORT = int(os.environ.get("JARVIS_TTS_PORT", "7739"))
BASE = f"http://127.0.0.1:{PORT}"
DAEMON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_daemon.py")
LOG = os.path.join(JARVIS_HOME, "daemon.log")
LOG_MAX_BYTES = 64 * 1024  # keep the daemon log bounded (see trim_log)


def venv_python():
    """Path to the venv interpreter, cross-platform."""
    win = os.path.join(JARVIS_HOME, "venv", "Scripts", "python.exe")
    nix = os.path.join(JARVIS_HOME, "venv", "bin", "python")
    return win if os.name == "nt" else nix


def health(timeout=1.0):
    try:
        urllib.request.urlopen(f"{BASE}/health", timeout=timeout)
        return True
    except Exception:
        return False


def trim_log():
    """Keep daemon.log bounded to its most recent LOG_MAX_BYTES.

    The log is append-only across every daemon (re)start, so without this a
    single old one-off error — e.g. a transient PortAudio -9986 from before a
    fix — lingers in the tail forever and looks like a recurring failure.
    Trimming on each cold start lets stale lines age out."""
    marker = b"[jarvis-ttsd] (older log lines trimmed)\n"
    try:
        if os.path.getsize(LOG) <= LOG_MAX_BYTES:
            return
        with open(LOG, "rb") as f:
            f.seek(-(LOG_MAX_BYTES - len(marker)), os.SEEK_END)
            tail = f.read()
        tail = tail.split(b"\n", 1)[1] if b"\n" in tail else tail  # drop partial line
        with open(LOG, "wb") as f:
            f.write(marker + tail)
    except OSError:
        pass


def ensure_daemon():
    if health():
        return True
    py = venv_python()
    if not (os.path.exists(py) and os.path.exists(DAEMON)):
        return False
    trim_log()
    with open(LOG, "ab") as logf:
        subprocess.Popen([py, DAEMON], stdout=logf, stderr=logf, start_new_session=True)
    deadline = time.time() + 60
    while time.time() < deadline:
        if health():
            return True
        time.sleep(0.5)
    return False


def speak_daemon(text, cfg, session_id=None):
    payload = {
        "text": text,
        "voice": cfg["voice"],
        "speed": cfg["speed"],
        "session_id": session_id or "",
    }
    req = urllib.request.Request(
        f"{BASE}/speak",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=30)


def speak_fallback(text, cfg):
    """Per-OS system-TTS fallback when the daemon is unavailable."""
    import fallback

    fallback.speak(text, cfg.get("say_voice"))


def main():
    text = sys.argv[1].strip() if len(sys.argv) > 1 else sys.stdin.read().strip()
    session_id = sys.argv[2] if len(sys.argv) > 2 else None
    if not text:
        return
    cfg = load_config(session_id)
    engine = str(cfg["engine"]).lower()
    try:
        if engine != "say" and ensure_daemon():
            speak_daemon(text, cfg, session_id)
            return
    except Exception:
        pass
    speak_fallback(text, cfg)


if __name__ == "__main__":
    main()
