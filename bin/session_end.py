#!/usr/bin/env python3
"""SessionEnd hook (Claude only). Stdlib-only.

Deletes this session's arming + override files when the session ends. Codex has
no session-end event; the daemon's age sweep (cleanup.sweep) covers it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cleanup import cleanup_session  # noqa: E402
from payload import get_session_id, read_stdin_json  # noqa: E402


def main():
    cleanup_session(get_session_id(read_stdin_json()))
    sys.exit(0)


if __name__ == "__main__":
    main()
