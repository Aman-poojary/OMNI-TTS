#!/usr/bin/env python3
"""Regression tests for cli.resolve_session. Stdlib-only:

    python3 tests/test_cli_session.py

Locks down the arm/speak session-id agreement. The `jarvis` CLI (called by the
/jarvis and /jarvis-on skills) must arm the SAME session id the Stop hook fires
with. The Stop hook reads session_id from its payload; Claude Code exports that
exact id as CLAUDE_CODE_SESSION_ID for the whole session process (same value as
the <id>.jsonl transcript). So resolution must prefer CLAUDE_CODE_SESSION_ID: it
is available the instant a skill's `!`-preprocessing runs — before the
UserPromptSubmit hook writes `last_session` — and is per-process, so a second
live session can't clobber it.

`last_session` is the CODEX fallback only (Codex has no such env var). Under
Claude Code (CLAUDECODE=1) it is never consulted: if CLAUDE_CODE_SESSION_ID is
missing there, resolution fails CLOSED (returns "") rather than guessing from
the single global `last_session`, which names whichever session prompted last
and would silently arm the WRONG session on a switch. CLAUDE_SESSION_ID is a
legacy last resort and is normally UNSET.
"""

import os
import sys
import tempfile

os.environ["JARVIS_HOME"] = tempfile.mkdtemp(prefix="jarvis-test-")
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
)
import config  # noqa: E402  (must import after JARVIS_HOME is set)
import cli  # noqa: E402


def check(name, cond):
    print(("PASS" if cond else "FAIL") + f"  {name}")
    return cond


def main():
    ok = True
    REAL = "6055006f-real-conversation-id"   # payload id == CLAUDE_CODE_SESSION_ID
    OTHER = "3e5e7c79-other-live-session"    # a different concurrently-active session

    # Start from a clean env (the real session running the test exports these).
    # CLAUDECODE is included so the Codex-fallback cases below model a genuine
    # non-Claude environment even when the test itself runs under Claude Code.
    for var in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID",
                "JARVIS_SESSION_ID", "CLAUDECODE"):
        os.environ.pop(var, None)

    # The core fix: CLAUDE_CODE_SESSION_ID is the payload id and must win, even
    # when `last_session` points at a DIFFERENT session (the concurrency clobber:
    # another live session submitted a prompt and overwrote the single global
    # file). Arming must still target THIS process's session.
    config.write_last_session(OTHER)
    os.environ["CLAUDE_CODE_SESSION_ID"] = REAL
    ok &= check("CLAUDE_CODE_SESSION_ID wins over a clobbered last_session",
                cli.resolve_session([]) == REAL)

    # Explicit --session always wins.
    ok &= check("--session overrides everything",
                cli.resolve_session(["--session", "explicit-id"]) == "explicit-id")

    # Fail-loud under Claude Code: if we know we're in Claude (CLAUDECODE=1) but
    # CLAUDE_CODE_SESSION_ID is missing, resolution must NOT fall back to the
    # global last_session (that would arm whichever session prompted last). It
    # returns "" so the CLI reports "no active session" instead of arming OTHER.
    del os.environ["CLAUDE_CODE_SESSION_ID"]
    os.environ["CLAUDECODE"] = "1"
    config.write_last_session(OTHER)
    ok &= check("Claude Code never guesses from last_session (fails closed)",
                cli.resolve_session([]) == "")
    del os.environ["CLAUDECODE"]

    # Codex fallback: no CLAUDE_CODE_SESSION_ID and NOT Claude Code, so
    # `last_session` (written by Codex's UserPromptSubmit hook) resolves it.
    config.write_last_session(REAL)
    ok &= check("last_session used when CLAUDE_CODE_SESSION_ID is unset",
                cli.resolve_session([]) == REAL)

    # Legacy env vars are the last resort, below last_session.
    os.remove(config.LAST_SESSION_PATH)
    os.environ["CLAUDE_SESSION_ID"] = "legacy-claude-id"
    ok &= check("CLAUDE_SESSION_ID used when nothing better exists",
                cli.resolve_session([]) == "legacy-claude-id")

    del os.environ["CLAUDE_SESSION_ID"]
    os.environ["JARVIS_SESSION_ID"] = "jarvis-env-id"
    ok &= check("JARVIS_SESSION_ID used as the final fallback",
                cli.resolve_session([]) == "jarvis-env-id")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
