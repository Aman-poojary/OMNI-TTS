#!/usr/bin/env python3
"""The ``jarvis`` CLI. Stdlib-only, runs under any python3.

The portability seam: skills call these subcommands instead of embedding shell,
so nothing is OS-specific. Session resolution order: --session flag, then
CLAUDE_SESSION_ID / JARVIS_SESSION_ID env, then the last active session recorded
by the UserPromptSubmit hook.

    jarvis arm | arm-once | disarm
    jarvis stop | warmup
    jarvis config [KEY VALUE]
    jarvis status
    jarvis say TEXT
"""

import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import armed  # noqa: E402
import config  # noqa: E402
import tts_client  # noqa: E402

_CASTS = {"speed": float, "max_chars": int}
_VALID_ENGINES = {"kokoro", "say"}


def resolve_session(argv):
    if "--session" in argv:
        i = argv.index("--session")
        if i + 1 < len(argv):
            return argv[i + 1]
    return (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("JARVIS_SESSION_ID")
        or config.read_last_session()
    )


def _post(path):
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"{tts_client.BASE}{path}", data=b""), timeout=5
        )
        return True
    except Exception:
        return False


def cmd_arm(sid, once=False):
    if not sid:
        print("no active session found; open a session and try again", file=sys.stderr)
        return 1
    (armed.arm_once if once else armed.arm)(sid)
    if tts_client.ensure_daemon():
        _post("/warmup")
    print(f"armed{' (one-shot)' if once else ''}: session {sid}")
    return 0


def cmd_disarm(sid):
    if sid:
        armed.disarm(sid)
    if tts_client.health():
        _post("/stop")
    print(f"disarmed: session {sid or '(none)'}")
    return 0


def cmd_stop(_sid):
    ok = _post("/stop") if tts_client.health() else False
    print("stopped" if ok else "daemon not running")
    return 0


def cmd_warmup(_sid):
    if tts_client.ensure_daemon():
        _post("/warmup")
        print("warming daemon")
        return 0
    print("daemon unavailable (venv/model missing?)", file=sys.stderr)
    return 1


def cmd_config(sid, key=None, value=None):
    if key is None:
        cfg = config.load_config(sid)
        print(f"session: {sid or '(none)'}")
        print(f"armed:   {armed.is_armed(sid)}")
        print(f"daemon:  {'running' if tts_client.health() else 'not running'}")
        for k in sorted(cfg):
            print(f"  {k}: {cfg[k]}")
        return 0
    if not sid:
        print("no active session to configure", file=sys.stderr)
        return 1
    if key not in config.DEFAULTS:
        print(f"unknown key {key!r}; valid: {', '.join(sorted(config.DEFAULTS))}", file=sys.stderr)
        return 1
    try:
        cast = _CASTS.get(key, str)(value)
    except (TypeError, ValueError):
        print(f"bad value for {key}: {value!r}", file=sys.stderr)
        return 1
    if key == "engine" and cast not in _VALID_ENGINES:
        print(f"engine must be one of {sorted(_VALID_ENGINES)}", file=sys.stderr)
        return 1
    config.set_session_value(sid, key, cast)
    print(f"set {key} = {cast} for session {sid}")
    return 0


def cmd_status(sid):
    return cmd_config(sid)


def cmd_say(sid, text):
    if not text:
        print("usage: jarvis say TEXT", file=sys.stderr)
        return 1
    cfg = config.load_config(sid)
    try:
        if str(cfg["engine"]).lower() != "say" and tts_client.ensure_daemon():
            tts_client.speak_daemon(text, cfg)
            return 0
    except Exception:
        pass
    tts_client.speak_fallback(text, cfg)
    return 0


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], [a for a in argv[1:] if a != "--session"]
    # strip a --session <id> pair from positional args
    if "--session" in argv:
        i = argv.index("--session")
        rest = [a for j, a in enumerate(argv[1:], start=1) if j not in (i, i + 1)]
    sid = resolve_session(argv)

    if cmd == "arm":
        return cmd_arm(sid)
    if cmd == "arm-once":
        return cmd_arm(sid, once=True)
    if cmd == "disarm":
        return cmd_disarm(sid)
    if cmd == "stop":
        return cmd_stop(sid)
    if cmd == "warmup":
        return cmd_warmup(sid)
    if cmd == "config":
        return cmd_config(sid, rest[0] if rest else None, rest[1] if len(rest) > 1 else None)
    if cmd == "status":
        return cmd_status(sid)
    if cmd == "say":
        return cmd_say(sid, " ".join(rest).strip())
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
