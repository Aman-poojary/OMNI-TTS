#!/usr/bin/env python3
"""Regression tests for payload.last_assistant_text. Stdlib-only:

    python3 tests/test_payload.py

Locks down the Stop-hook race: the hook can fire before the provider flushes
the new reply to the transcript. Reading "last assistant text in the file"
would re-speak the PREVIOUS reply; the shim must return "" (caller retries)
until a reply newer than the latest user prompt appears, and must never pick
up sidechain (subagent) text.
"""

import json
import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
)
import payload  # noqa: E402


def entry(etype, content, sidechain=False):
    e = {"type": etype, "message": {"role": etype, "content": content}}
    if sidechain:
        e["isSidechain"] = True
    return json.dumps(e)


REPLY1 = "At your service, sir.\n\n\U0001f50a At your service, sir."
REPLY2 = "Voice replies are on.\n\n\U0001f50a Voice replies are on, sir."

MID_RACE = [
    entry("user", "<command-message>jarvis</command-message>"),
    entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]),
    entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
    entry("assistant", [{"type": "text", "text": REPLY1}]),
    # second command submitted; its reply not flushed yet
    entry("user", "<command-message>jarvis-on</command-message>"),
    entry("assistant", [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {}}]),
    entry("user", [{"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]),
]


def write_transcript(lines):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def check(name, cond):
    print(("PASS" if cond else "FAIL") + f"  {name}")
    return cond


def main():
    ok = True

    path = write_transcript(MID_RACE)
    got = payload.last_assistant_text({"transcript_path": path})
    ok &= check("mid-race returns empty, never the previous reply", got == "")

    with open(path, "a") as f:
        f.write(entry("assistant", [{"type": "text", "text": REPLY2}]) + "\n")
        f.write(entry("assistant", [{"type": "text", "text": "subagent noise"}],
                      sidechain=True) + "\n")
    got = payload.last_assistant_text({"transcript_path": path})
    ok &= check("flushed reply is returned", got.startswith("Voice replies are on"))
    ok &= check("sidechain text is ignored", "subagent" not in got)
    os.remove(path)

    # simple single-turn transcript still works
    path = write_transcript([
        entry("user", "hello"),
        entry("assistant", [{"type": "text", "text": REPLY1}]),
    ])
    got = payload.last_assistant_text({"transcript_path": path})
    ok &= check("single turn returns its reply", got.startswith("At your service"))
    os.remove(path)

    # user text as a content block (not a string) is still a turn boundary
    path = write_transcript([
        entry("user", "hello"),
        entry("assistant", [{"type": "text", "text": REPLY1}]),
        entry("user", [{"type": "text", "text": "second question"}]),
    ])
    got = payload.last_assistant_text({"transcript_path": path})
    ok &= check("block-style prompt resets the reply", got == "")
    os.remove(path)

    # inline fallback (Codex-style payload, no transcript) untouched
    got = payload.last_assistant_text({"last_assistant_message": "inline reply"})
    ok &= check("inline fallback still works", got == "inline reply")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
