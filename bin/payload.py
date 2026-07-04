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


def _from_transcript(transcript_path):
    """Return the last assistant message's text from a JSONL transcript."""
    last_text = ""
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("type") != "assistant":
                    continue
                text = _text_from_content(entry.get("message", {}).get("content", ""))
                if text.strip():
                    last_text = text.strip()
    except OSError:
        return ""
    return last_text


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
