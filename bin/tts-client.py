#!/usr/bin/env python3
"""
Client for the JARVIS Kokoro TTS daemon. Stdlib-only, runs on any python3.

Called detached by speak.py with the cleaned text as argv[1].
Ensures the daemon is running (starting it from the venv if needed), sends
the text, and falls back to macOS `say` if the daemon can't be reached.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jarvis_config import load_config  # noqa: E402

PORT = int(os.environ.get("JARVIS_TTS_PORT", "7739"))
BASE = f"http://127.0.0.1:{PORT}"
VENV_PY = os.path.expanduser("~/.claude/jarvis/venv/bin/python")
DAEMON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts-daemon.py")
LOG = os.path.expanduser("~/.claude/jarvis/daemon.log")


def health(timeout=1.0):
    try:
        urllib.request.urlopen(f"{BASE}/health", timeout=timeout)
        return True
    except Exception:
        return False


def ensure_daemon():
    if health():
        return True
    if not (os.path.exists(VENV_PY) and os.path.exists(DAEMON)):
        return False
    with open(LOG, "ab") as logf:
        subprocess.Popen(
            [VENV_PY, DAEMON],
            stdout=logf,
            stderr=logf,
            start_new_session=True,
        )
    deadline = time.time() + 60
    while time.time() < deadline:
        if health():
            return True
        time.sleep(0.5)
    return False


def speak_daemon(text):
    req = urllib.request.Request(
        f"{BASE}/speak",
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=30)


def speak_say(text):
    if sys.platform != "darwin":
        return
    voice = os.environ.get("JARVIS_VOICE") or load_config()["say_voice"]
    subprocess.run(["say", "-v", voice, text])


def main():
    text = sys.argv[1].strip() if len(sys.argv) > 1 else sys.stdin.read().strip()
    if not text:
        return
    try:
        if ensure_daemon():
            speak_daemon(text)
            return
    except Exception:
        pass
    speak_say(text)


if __name__ == "__main__":
    main()
