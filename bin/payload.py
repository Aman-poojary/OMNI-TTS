"""Provider payload shim. Stdlib-only.

Reads the hook event JSON (stdin) and extracts what JARVIS needs regardless of
provider: the session id and the last assistant reply text.

Claude Code's Stop payload carries ``session_id`` and ``transcript_path`` (a
JSONL file whose last ``assistant`` entry holds the reply). Codex has no
transcript path in the same form; its Stop payload is verified in Task 08, so
this module also looks for the reply inline. Centralizing the differences keeps
the hooks provider-neutral.
"""

import json
import os
import sys


def read_stdin_json():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def get_session_id(data):
    return data.get("session_id") or data.get("sessionId") or ""


def _text_from_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return " ".join(p for p in parts if p)
    return ""


# Long-running sessions accumulate transcripts of tens of MB; the reply we
# want is at the end, and a full scan can blow the Stop hook's timeout.
TAIL_BYTES = 256 * 1024


def _is_user_prompt(entry):
    """A real user turn boundary: typed text (string content or a text block),
    not a tool_result feeding back into the same turn."""
    content = entry.get("message", {}).get("content", "")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "text" for b in content
        )
    return False


def _scan_lines(lines):
    """Return (text, saw_prompt): the last assistant text that appears AFTER
    the newest user prompt. The Stop hook can fire before the provider flushes
    the new reply to the transcript; treating pre-prompt text as current would
    re-speak the PREVIOUS reply, so it returns "" and lets the caller retry.
    Sidechain (subagent) entries never belong to the spoken conversation."""
    last_text = ""
    saw_prompt = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("isSidechain"):
            continue
        etype = entry.get("type")
        if etype == "user" and _is_user_prompt(entry):
            saw_prompt = True
            last_text = ""  # anything before this prompt is a stale reply
            continue
        if etype != "assistant":
            continue
        text = _text_from_content(entry.get("message", {}).get("content", ""))
        if text.strip():
            last_text = text.strip()
    return last_text, saw_prompt


def _from_transcript(transcript_path):
    """Return the current reply's text from a JSONL transcript, or "" if the
    reply has not been flushed yet (the caller may retry).

    Reads only the file's tail; falls back to a full scan when the current
    turn is so large that its user prompt lies beyond the final TAIL_BYTES.
    """
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as f:
            truncated = size > TAIL_BYTES
            if truncated:
                f.seek(size - TAIL_BYTES)
            data = f.read()
        if truncated:
            # drop the (probably partial) first line of the window
            data = data.split(b"\n", 1)[1] if b"\n" in data else b""
        text, saw_prompt = _scan_lines(
            data.decode("utf-8", errors="ignore").splitlines()
        )
        if text:
            return text
        if truncated and not saw_prompt:
            with open(
                transcript_path, "r", encoding="utf-8", errors="ignore"
            ) as f:
                return _scan_lines(f)[0]
        return ""
    except OSError:
        return ""


def last_assistant_text(data):
    """Best-effort spoken-source text across providers."""
    tp = data.get("transcript_path") or ""
    if tp and os.path.exists(tp):
        text = _from_transcript(tp)
        if text:
            return text
    # Inline fallbacks (Codex / providers without a transcript file).
    for key in ("last_assistant_message", "assistant_message", "last_message", "message"):
        val = data.get(key)
        text = _text_from_content(val.get("content", val) if isinstance(val, dict) else val)
        if text and text.strip():
            return text.strip()
    return ""
