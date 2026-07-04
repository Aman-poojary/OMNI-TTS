"""Per-session arming flags under ~/.jarvis/armed/. Stdlib-only.

Two flag files per session id:
    <sid>        persistent  (/jarvis-on ... /jarvis-off)
    <sid>.once   one-shot    (/jarvis; consumed after one reply)

Arming is per-session so one session speaking never affects another.

There is also one non-session file, ``.pending``: an arm/disarm intent written
by a context that cannot know the real session id (skill preprocessing runs
before the UserPromptSubmit hook records ``last_session``, so on a session's
first prompt that fallback still names the PREVIOUS session). The next hook
that receives the true session id (remind.py, or speak.py as backstop) claims
the intent and applies it to its own session.
"""

import os
import time

from config import ARMED_DIR, ensure_dirs, sanitize_session_id

PENDING_MAX_AGE_SECS = 120


def _pending():
    return os.path.join(ARMED_DIR, ".pending")


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


def refresh(session_id):
    """Touch this session's flag mtimes so the age sweep never disarms a
    session that is still actively prompting."""
    now = None
    for path in (_persistent(session_id), _once(session_id)):
        try:
            os.utime(path, now)
        except OSError:
            pass


def set_pending(mode):
    """Record an arm/disarm intent ("on" | "once" | "off") to be bound to the
    next session whose hook claims it."""
    ensure_dirs()
    with open(_pending(), "w") as f:
        f.write(mode)


def claim_pending(session_id):
    """Bind a fresh pending intent to this session and apply it. Returns the
    mode applied, or None if there was nothing (fresh) to claim."""
    if not session_id:
        return None
    path = _pending()
    try:
        stale = time.time() - os.path.getmtime(path) > PENDING_MAX_AGE_SECS
        with open(path) as f:
            mode = f.read().strip()
        os.remove(path)
    except OSError:
        return None
    if stale or mode not in ("on", "once", "off"):
        return None
    {"on": arm, "once": arm_once, "off": disarm}[mode](session_id)
    return mode


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
