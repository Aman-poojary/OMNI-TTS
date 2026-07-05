#!/usr/bin/env python3
"""The ``jarvis`` CLI. Stdlib-only, runs under any python3.

The portability seam: skills call these subcommands instead of embedding shell,
so nothing is OS-specific. Session resolution order: --session flag, then
CLAUDE_CODE_SESSION_ID env (Claude Code sets it per process and it equals the
hook payload session_id), then the last active session recorded by the
UserPromptSubmit hook (the Codex fallback), then the legacy env vars.

    jarvis arm | arm-once | disarm   (aliases: on / once / off)
    jarvis stop [--all] | warmup
    jarvis config [KEY VALUE]
    jarvis output [NUMBER|NAME|default]   (list / choose the output device)
    jarvis status
    jarvis say TEXT
    jarvis ui
"""

import json
import os
import subprocess
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
    # CLAUDE_CODE_SESSION_ID is set by Claude Code for the whole session process
    # and is EXACTLY the payload session_id the Stop hook receives (same value as
    # the <id>.jsonl transcript). Because the process env is available the instant
    # a skill's `!`-preprocessing runs — before the UserPromptSubmit hook writes
    # `last_session`, and unaffected by any other concurrently active session — it
    # is the correct primary: it fixes both the ordering race (arm running before
    # `last_session` is written) and the concurrency clobber (a single global
    # `last_session` file can't serve two live sessions at once).
    #
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if sid:
        return sid
    # Under Claude Code the env var above is authoritative and per-process, so if
    # it is set we already returned it. If we are in Claude Code (CLAUDECODE=1)
    # but it is somehow missing, we must NOT fall through to the global
    # `last_session`: that file names whichever session prompted most recently,
    # so with several live sessions guessing from it silently arms the WRONG
    # session on a switch. Fail closed (return "") and let the caller report it.
    if os.environ.get("CLAUDECODE"):
        return ""
    # Codex path only: no per-process id env var, so `last_session` (written by
    # its UserPromptSubmit hook) is the intended resolver. The legacy
    # CLAUDE_SESSION_ID / JARVIS_SESSION_ID vars are last-resort.
    return (
        config.read_last_session()
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("JARVIS_SESSION_ID")
    )


def warm_detached():
    """Ensure the daemon is up and warm in a detached process, so callers never
    block on the cold model load (~seconds). Reused by ``arm`` and the prompt
    hook; a no-op cost when the daemon is already warm (a quick health + warmup
    round-trip that exits immediately)."""
    try:
        subprocess.Popen(
            [sys.executable or "python3", os.path.abspath(__file__), "warmup"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def _post(path, timeout=5, body=None):
    try:
        data = json.dumps(body).encode("utf-8") if body is not None else b""
        urllib.request.urlopen(
            urllib.request.Request(f"{tts_client.BASE}{path}", data=data), timeout=timeout
        )
        return True
    except Exception:
        return False


def cmd_arm(sid, once=False):
    if not sid:
        print("no active session found; open a session and try again", file=sys.stderr)
        return 1
    (armed.arm_once if once else armed.arm)(sid)
    # Warm in a detached process: the daemon's cold spawn + model load can take
    # seconds, and blocking here freezes the /jarvis-on slash command. The
    # daemon self-warms at boot; this also covers the already-running-but-cold
    # case. Warmth catches up well before the first reply's Stop hook fires.
    warm_detached()
    print(f"armed{' (one-shot)' if once else ''}: session {sid}")
    return 0


def cmd_disarm(sid):
    if sid:
        armed.disarm(sid)
    if tts_client.health():
        # scoped: silencing one session must not cut another session's audio
        _post("/stop", body={"session_id": sid} if sid else None)
    print(f"disarmed: session {sid or '(none)'}")
    return 0


def cmd_stop(sid, everything=False):
    body = {"session_id": sid} if sid and not everything else None
    ok = _post("/stop", body=body) if tts_client.health() else False
    scope = "all sessions" if body is None else f"session {sid}"
    print(f"stopped ({scope})" if ok else "daemon not running")
    return 0


def cmd_ui(_sid):
    url = f"{tts_client.BASE}/ui"
    if not tts_client.ensure_daemon():
        print("daemon unavailable (venv/model missing?)", file=sys.stderr)
        return 1
    print(url)
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        pass
    return 0


def _get(path, timeout=5):
    try:
        with urllib.request.urlopen(f"{tts_client.BASE}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def cmd_output(sid, choice=None):
    """List output devices, or select one (by number, name, or 'default')."""
    if not tts_client.ensure_daemon():
        print("daemon unavailable (venv/model missing?)", file=sys.stderr)
        return 1
    info = _get("/devices")
    if not info:
        print("could not read devices from daemon", file=sys.stderr)
        return 1
    devices = info.get("devices", [])

    if choice is None:
        selected = info.get("selected", "")
        print("Play voice through:  (choose with: jarvis output <number|name|default>)\n")
        star = "*" if not selected else " "
        print(f"  {star} 0. System default"
              + (f"  [{next((d['name'] for d in devices if d['default']), '?')}]" if devices else ""))
        for n, d in enumerate(devices, start=1):
            cur = "*" if selected and selected.lower() in d["name"].lower() else " "
            tag = "  (system default)" if d["default"] else ""
            print(f"  {cur} {n}. {d['name']}{tag}")
        print("\n  * = currently selected")
        return 0

    # Resolve the choice to a device name ("" means system default).
    c = choice.strip()
    if c.lower() in ("default", "system", "0", ""):
        device = ""
    elif c.isdigit():
        idx = int(c) - 1
        if not (0 <= idx < len(devices)):
            print(f"no device numbered {c}; run 'jarvis output' to list", file=sys.stderr)
            return 1
        device = devices[idx]["name"]
    else:
        match = next((d["name"] for d in devices if c.lower() in d["name"].lower()), None)
        if not match:
            print(f"no device matching {c!r}; run 'jarvis output' to list", file=sys.stderr)
            return 1
        device = match
    _post("/output_device", body={"device": device})
    print(f"voice will play through: {device or 'system default'}")
    return 0


def cmd_warmup(_sid):
    if tts_client.ensure_daemon():
        _post("/warmup", timeout=90)
        print("daemon warm")
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

    if cmd in ("arm", "on"):
        return cmd_arm(sid)
    if cmd in ("arm-once", "once"):
        return cmd_arm(sid, once=True)
    if cmd in ("disarm", "off"):
        return cmd_disarm(sid)
    if cmd == "stop":
        return cmd_stop(sid, everything="--all" in rest)
    if cmd == "warmup":
        return cmd_warmup(sid)
    if cmd in ("output", "device", "devices"):
        return cmd_output(sid, " ".join(rest).strip() or None)
    if cmd == "ui":
        return cmd_ui(sid)
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
