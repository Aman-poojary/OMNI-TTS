#!/usr/bin/env python3
"""UserPromptSubmit hook. Stdlib-only, runs under any python3.

When THIS session is armed, inject a reminder so the assistant ends its reply
with the 🔊 voice-summary line the Stop hook speaks. Injects nothing when the
session is disarmed, so normal sessions see zero noise.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armed import is_armed  # noqa: E402
from config import write_last_session  # noqa: E402
from payload import get_session_id, read_stdin_json  # noqa: E402


def main():
    data = read_stdin_json()
    session_id = get_session_id(data)
    write_last_session(session_id)  # let the CLI resolve "this session"
    if is_armed(session_id):
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
                    "the user as 'sir' where natural."
                ),
            }
        }))
    sys.exit(0)


if __name__ == "__main__":
    main()
