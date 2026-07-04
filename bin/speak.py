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
from armed import should_speak  # noqa: E402
from config import JARVIS_HOME, load_config  # noqa: E402
from payload import get_session_id, last_assistant_text, read_stdin_json  # noqa: E402
from textproc import clean_for_speech, pick_speech_source  # noqa: E402

CLIENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_client.py")

POLL_DEADLINE_SECS = 6.0


def debug_log(msg):
    try:
        with open(os.path.join(JARVIS_HOME, "hook.log"), "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def resolve_speech(data, deadline_secs=POLL_DEADLINE_SECS, poll_interval=0.2):
    """Return (raw, spoken) for the CURRENT reply, polling until its 🔊 source
    is visible.

    The provider may flush the final reply a beat after Stop fires, and in a
    multi-tool turn the mid-turn narration messages are already flushed — so a
    non-empty read is NOT proof the reply is current. Poll until a speakable
    🔊 paragraph appears; on timeout fail closed (a genuinely marker-less
    reply stays silent by design)."""
    deadline = time.time() + deadline_secs
    raw = last_assistant_text(data)
    while not pick_speech_source(raw) and time.time() < deadline:
        time.sleep(poll_interval)
        raw = last_assistant_text(data)
    return raw, clean_for_speech(pick_speech_source(raw))


def main():
    data = read_stdin_json()
    session_id = get_session_id(data)
    if not should_speak(session_id):
        sys.exit(0)

    raw, text = resolve_speech(data)
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
