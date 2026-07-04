"""Per-session arming flags under ~/.jarvis/armed/. Stdlib-only.

Two flag files per session id:
    <sid>        persistent  (/jarvis-on ... /jarvis-off)
    <sid>.once   one-shot    (/jarvis; consumed after one reply)

Arming is per-session so one session speaking never affects another.
"""

import os

from config import ARMED_DIR, ensure_dirs, sanitize_session_id


def _persistent(session_id):
    return os.path.join(ARMED_DIR, sanitize_session_id(session_id))


def _once(session_id):
    return os.path.join(ARMED_DIR, sanitize_session_id(session_id) + ".once")


def _touch(path):
    ensure_dirs()
    with open(path, "w"):
        pass


def _rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


def arm(session_id):
    """Speak every reply for this session until disarmed."""
    _touch(_persistent(session_id))


def arm_once(session_id):
    """Speak the next reply for this session, then auto-disarm."""
    _touch(_once(session_id))


def disarm(session_id):
    """Remove both flags for this session (never touches other sessions)."""
    _rm(_persistent(session_id))
    _rm(_once(session_id))


def is_armed(session_id):
    """Non-consuming check — used by the UserPromptSubmit hook."""
    if not session_id:
        return False
    return os.path.exists(_persistent(session_id)) or os.path.exists(_once(session_id))


def should_speak(session_id):
    """Consuming check for the Stop hook: persistent stays armed; one-shot is
    consumed. Returns True if this reply should be spoken."""
    if not session_id:
        return False
    if os.path.exists(_persistent(session_id)):
        return True
    if os.path.exists(_once(session_id)):
        _rm(_once(session_id))
        return True
    return False
