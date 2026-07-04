#!/usr/bin/env python3
"""SessionStart cleanup hook for providers without SessionEnd.

Codex does not expose a SessionEnd hook. Running the age-based sweep on
SessionStart gives stale per-session JARVIS state another cleanup path even
when the TTS daemon is not currently alive.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cleanup import sweep  # noqa: E402


def main():
    sweep()
    return 0


if __name__ == "__main__":
    sys.exit(main())
