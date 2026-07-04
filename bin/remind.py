#!/usr/bin/env python3
"""
UserPromptSubmit hook: when JARVIS voice mode is armed (a flag file exists
in ~/.claude/jarvis/), inject a reminder so Claude reliably ends its reply
with the 🔊 voice-summary line the Stop hook speaks. Injects nothing when
voice is off, so normal sessions see zero noise.
"""

import json
import os
import sys

JARVIS_DIR = os.path.expanduser("~/.claude/jarvis")


def main():
    on = os.path.exists(os.path.join(JARVIS_DIR, "speak_on"))
    once = os.path.exists(os.path.join(JARVIS_DIR, "speak_once"))
    if on or once:
        mode = "persistent" if on else "one-shot"
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    f"JARVIS voice mode is armed ({mode}): a Stop hook will "
                    "speak your reply aloud, and it speaks ONLY the final "
                    "paragraph that starts with \U0001f50a. Write that "
                    "paragraph as JARVIS answering Tony Stark: directly "
                    "answer what the user asked, stating the actual "
                    "findings, numbers, names, and conclusions — not a "
                    "meta-description of the work you did. Straight to the "
                    "point, no filler; as short or as long as a complete "
                    "answer requires. Plain conversational prose only: no "
                    "markdown, no code, no file paths. Address the user as "
                    "'sir' where natural."
                ),
            }
        }))
    sys.exit(0)


if __name__ == "__main__":
    main()
