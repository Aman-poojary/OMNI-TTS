#!/usr/bin/env python3
"""UserPromptSubmit hook. Stdlib-only, runs under any python3.

When THIS session is armed, inject a reminder so the assistant ends its reply
with the 🔊 voice-summary line the Stop hook speaks. Injects nothing when the
session is disarmed, so normal sessions see zero noise.

Also the barge-in point: a new prompt in an armed session cancels THAT
session's queued/playing speech (the reply it supersedes), without touching
other sessions' audio.
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armed import is_armed, refresh  # noqa: E402
from config import write_last_session  # noqa: E402
from payload import get_session_id, read_stdin_json  # noqa: E402


def barge_in(session_id):
    """Best-effort session-scoped /stop; instant no-op when the daemon is down."""
    port = os.environ.get("JARVIS_TTS_PORT", "7739")
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"http://127.0.0.1:{port}/stop",
                data=json.dumps({"session_id": session_id}).encode("utf-8"),
            ),
            timeout=1,
        )
    except Exception:
        pass


def main():
    data = read_stdin_json()
    session_id = get_session_id(data)
    write_last_session(session_id)  # let the CLI resolve "this session"
    if is_armed(session_id):
        refresh(session_id)     # active session: keep the age sweep away
        barge_in(session_id)    # new prompt supersedes this session's speech
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    "JARVIS voice mode is armed for this session: a Stop hook "
                    "will speak your reply aloud, and it speaks ONLY the final "
                    "paragraph that starts with \U0001f50a. Write that "
                    "paragraph as JARVIS answering Tony Stark: directly answer "
                    "what the user asked, stating the actual findings, numbers, "
                    "names, and conclusions — not a meta-description of the work "
                    "you did. Straight to the point, no filler; as short or as "
                    "long as a complete answer requires. Plain conversational "
                    "prose only: no markdown, no code, no file paths. Address "
                    "the user as 'sir' where natural. If the user asks to stop "
                    "talking, run `python3 ~/.jarvis/bin/cli.py stop`; to turn "
                    "voice replies off, run `python3 ~/.jarvis/bin/cli.py "
                    "disarm`."
                ),
            }
        }))
    sys.exit(0)


if __name__ == "__main__":
    main()
