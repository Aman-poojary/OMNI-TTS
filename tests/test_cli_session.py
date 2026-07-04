#!/usr/bin/env python3
"""Regression tests for cli.resolve_session. Stdlib-only:

    python3 tests/test_cli_session.py

Locks down the arm/speak session-id agreement. The `jarvis` CLI (called by the
/jarvis and /jarvis-on skills) must arm the SAME session id the Stop hook will
fire with. The Stop hook reads session_id from its payload; the UserPromptSubmit
hook persists that exact id to `last_session`. So resolution must prefer
`last_session` over CLAUDE_SESSION_ID — in the Claude Code CLI, CLAUDE_SESSION_ID
is a different id namespace than the hook payload, and trusting it first armed a
session the Stop hook never sees (reply shows 🔊 but no audio plays).
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
    REAL = "6055006f-real-conversation-id"   # what the Stop hook uses
    ENV = "3e5e7c79-cli-env-id"              # CLAUDE_SESSION_ID in the CLI

    # The reported bug: last_session is correct, but a mismatched
    # CLAUDE_SESSION_ID used to win and arm the wrong session.
    config.write_last_session(REAL)
    os.environ["CLAUDE_SESSION_ID"] = ENV
    os.environ.pop("JARVIS_SESSION_ID", None)
    ok &= check("last_session wins over mismatched CLAUDE_SESSION_ID",
                cli.resolve_session([]) == REAL)

    # Explicit --session always wins.
    ok &= check("--session overrides everything",
                cli.resolve_session(["--session", "explicit-id"]) == "explicit-id")

    # Env is still a fallback when no prompt has been submitted yet.
    os.remove(config.LAST_SESSION_PATH)
    ok &= check("CLAUDE_SESSION_ID used when last_session is empty",
                cli.resolve_session([]) == ENV)

    del os.environ["CLAUDE_SESSION_ID"]
    os.environ["JARVIS_SESSION_ID"] = "jarvis-env-id"
    ok &= check("JARVIS_SESSION_ID used as last resort",
                cli.resolve_session([]) == "jarvis-env-id")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
