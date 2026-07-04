#!/usr/bin/env python3
"""Stop hook — the JARVIS orchestrator. Stdlib-only, runs under any python3.

Fires on every Stop event but speaks only when THIS session is armed
(``~/.jarvis/armed/<session_id>`` persistent, or ``<session_id>.once`` one-shot,
which is consumed here). Reads the last assistant reply from the provider
payload, reduces it to spoken prose, and hands it to the detached TTS client
with the session's effective voice/speed. Always exits 0 — never blocks the
provider from finishing.
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armed import claim_pending, should_speak  # noqa: E402
from config import JARVIS_HOME, load_config  # noqa: E402
from payload import get_session_id, last_assistant_text, read_stdin_json  # noqa: E402
from textproc import clean_for_speech, pick_speech_source  # noqa: E402

CLIENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_client.py")


def debug_log(msg):
    try:
        with open(os.path.join(JARVIS_HOME, "hook.log"), "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def main():
    data = read_stdin_json()
    session_id = get_session_id(data)
    # Backstop for providers whose prompt hook didn't fire for the arming
    # command: the turn's Stop still knows the true session id, so a pending
    # arm/disarm intent left by skill preprocessing binds here instead.
    claim_pending(session_id)
    if not should_speak(session_id):
        sys.exit(0)

    # The provider may flush the new reply to the transcript a beat after Stop
    # fires; payload returns "" until the post-prompt reply is visible, so poll
    # briefly rather than re-speak the previous reply. Stay silent on timeout.
    deadline = time.time() + 6.0
    raw = last_assistant_text(data)
    while not raw and time.time() < deadline:
        time.sleep(0.2)
        raw = last_assistant_text(data)

    text = clean_for_speech(pick_speech_source(raw))
    debug_log(f"session={session_id!r} raw_len={len(raw)} spoken_len={len(text)}")
    if not text:
        sys.exit(0)

    cfg = load_config(session_id)
    max_chars = int(cfg["max_chars"])
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + ". Response truncated, sir."

    # Detach the speaker so the hook returns immediately. The client loads this
    # session's effective config and talks to the daemon (or the fallback).
    subprocess.Popen(
        [sys.executable or "python3", CLIENT, text, session_id or ""],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
