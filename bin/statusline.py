#!/usr/bin/env python3
"""Claude Code status-line segment for JARVIS. Stdlib-only, must stay fast —
Claude runs the statusLine command every few hundred ms.

Reads the statusLine JSON from stdin (session_id) and prints one segment:

    🔊 JARVIS on · ⚡ ▶        armed, daemon warm, currently speaking
    🔊 JARVIS once · ⚡        one-shot armed, daemon warm
    🔇 JARVIS off · session –  disarmed and session state cleaned/swept

Symbols: ⚡ daemon warm · ○ daemon up, model cold · ✗ daemon down · ▶ speaking.
Used standalone as the whole statusLine command, or appended to an existing
statusline script (see adapters/claude/register.py).
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import ARMED_DIR, SESSIONS_DIR, sanitize_session_id  # noqa: E402

PORT = os.environ.get("JARVIS_TTS_PORT", "7739")

DIM = "\033[38;5;245m"
GREEN = "\033[38;5;71m"
YELLOW = "\033[38;5;179m"
RED = "\033[38;5;167m"
RESET = "\033[0m"


def daemon_status():
    """(symbol, speaking) with a tight timeout so the status line never lags."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/status", timeout=0.2) as r:
            s = json.load(r)
        return ("⚡" if s.get("warmed") else "○"), bool(s.get("speaking"))
    except Exception:
        return "✗", False


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    sid = sanitize_session_id(data.get("session_id") or "")

    on = sid and os.path.exists(os.path.join(ARMED_DIR, sid))
    once = sid and os.path.exists(os.path.join(ARMED_DIR, sid + ".once"))
    has_state = on or once or (
        sid and os.path.exists(os.path.join(SESSIONS_DIR, sid + ".json"))
    )

    if on or once:
        mode = "on" if on else "once"
        symbol, speaking = daemon_status()
        color = GREEN if symbol == "⚡" else YELLOW if symbol == "○" else RED
        seg = f"{GREEN}🔊 JARVIS {mode}{RESET} {color}{symbol}{RESET}"
        if speaking:
            seg += f" {GREEN}▶{RESET}"
    else:
        # Disarmed: skip the HTTP probe, show whether session state survives.
        state = "session ✓" if has_state else "session –"
        seg = f"{DIM}🔇 JARVIS off · {state}{RESET}"

    print(seg)


if __name__ == "__main__":
    main()
