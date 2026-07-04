"""Session-file cleanup. Stdlib-only.

Touches ONLY ~/.jarvis/ files (arming flags + per-session overrides). Provider
transcripts/history (~/.claude/projects/**, ~/.codex/**) are never touched, so
resuming an old session stays safe.

Two triggers:
  - cleanup_session(id): exact removal on Claude's SessionEnd.
  - sweep(): 6-hour age-based backstop for Codex (no session-end) and crashes.
"""

import os
import time

from config import ARMED_DIR, SESSIONS_DIR, sanitize_session_id

MAX_AGE_SECS = 6 * 3600


def _rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


def cleanup_session(session_id):
    """Remove one session's arming + override files."""
    sid = sanitize_session_id(session_id)
    if not sid:
        return
    _rm(os.path.join(ARMED_DIR, sid))
    _rm(os.path.join(ARMED_DIR, sid + ".once"))
    _rm(os.path.join(SESSIONS_DIR, sid + ".json"))


def sweep(max_age=MAX_AGE_SECS):
    """Delete arming/override files older than max_age. Returns count removed."""
    now = time.time()
    removed = 0
    for d in (ARMED_DIR, SESSIONS_DIR):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            path = os.path.join(d, name)
            try:
                if now - os.path.getmtime(path) > max_age:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
    return removed
