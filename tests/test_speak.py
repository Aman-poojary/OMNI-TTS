#!/usr/bin/env python3
"""Regression tests for speak.resolve_speech. Stdlib-only:

    python3 tests/test_speak.py

Locks down the multi-tool-turn Stop race: mid-turn narration messages are
flushed to the transcript BEFORE the final 🔊 reply, so when Stop fires the
hook's first read returns non-empty text that is NOT the current reply.
Polling only "until non-empty" grabbed that narration, found no 🔊 marker,
and failed closed — silence even though the final reply carried the marker.
resolve_speech must keep polling until a speakable 🔊 source appears.
"""

import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
)
import speak  # noqa: E402


def entry(etype, content):
    return json.dumps({"type": etype, "message": {"role": etype, "content": content}})


NARRATION = "Let me verify the fix against the same real transcript."
FINAL = "Full technical detail here.\n\n\U0001f50a All fixed, sir."

# A long tool-using turn as it looks the instant Stop fires: the narration is
# flushed, the final reply is not.
MID_TURN = [
    entry("user", "why is the speech not coming out now?"),
    entry("assistant", [{"type": "text", "text": NARRATION}]),
    entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]),
    entry("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
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

    # Final reply flushes 0.5s after Stop: the hook must wait for the marker,
    # not settle for the already-flushed narration.
    path = write_transcript(MID_TURN)

    def flush_final():
        time.sleep(0.5)
        with open(path, "a") as f:
            f.write(entry("assistant", [{"type": "text", "text": FINAL}]) + "\n")

    t = threading.Thread(target=flush_final)
    t.start()
    raw, text = speak.resolve_speech({"transcript_path": path}, deadline_secs=3.0)
    t.join()
    ok &= check("race: waits past mid-turn narration for the 🔊 reply",
                text == "All fixed, sir.")
    os.remove(path)

    # Marker already flushed: returns immediately, no needless polling.
    path = write_transcript(MID_TURN + [
        entry("assistant", [{"type": "text", "text": FINAL}]),
    ])
    started = time.time()
    raw, text = speak.resolve_speech({"transcript_path": path}, deadline_secs=3.0)
    ok &= check("flushed reply returned immediately",
                text == "All fixed, sir." and time.time() - started < 1.0)
    os.remove(path)

    # Reply genuinely has no 🔊 line: fail closed (empty) after the deadline.
    path = write_transcript(MID_TURN)
    raw, text = speak.resolve_speech(
        {"transcript_path": path}, deadline_secs=0.5, poll_interval=0.1
    )
    ok &= check("marker-less turn still fails closed", text == "")
    os.remove(path)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
