#!/usr/bin/env python3
"""
JARVIS-style TTS Stop hook for Claude Code (macOS).

Fires on every Stop event, but only speaks when armed:
  ~/.claude/jarvis/speak_once  -> speak this one reply, then disarm (deleted)
  ~/.claude/jarvis/speak_on    -> speak every reply until removed (/jarvis-off)

The /jarvis* skills create/remove these flag files. With no flag present
this script exits immediately, so normal sessions are unaffected.

Settings come from ~/.claude/jarvis/config.json (engine, voices, speed,
max_chars); env vars override per-run:
  JARVIS_ENGINE     -> "kokoro" (daemon) or "say"
  JARVIS_VOICE      -> macOS `say` voice name
  JARVIS_RATE       -> `say` speech rate in words/min
  JARVIS_MAX_CHARS  -> truncate spoken text beyond this
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jarvis_config import load_config  # noqa: E402

JARVIS_DIR = os.path.expanduser("~/.claude/jarvis")
FLAG_ONCE = os.path.join(JARVIS_DIR, "speak_once")
FLAG_ON = os.path.join(JARVIS_DIR, "speak_on")


def armed():
    """Return True if we should speak; consume the one-shot flag."""
    if os.path.exists(FLAG_ON):
        return True
    if os.path.exists(FLAG_ONCE):
        try:
            os.remove(FLAG_ONCE)
        except OSError:
            pass
        return True
    return False


def read_hook_input():
    """Claude Code sends the event JSON on stdin."""
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def get_last_assistant_text(transcript_path):
    """Parse the JSONL transcript and return the text of the last assistant reply."""
    if not transcript_path or not os.path.exists(transcript_path):
        return ""

    last_text = ""
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
            content = entry.get("message", {}).get("content", "")

            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                text = " ".join(p for p in parts if p)
            else:
                text = ""

            if text.strip():
                last_text = text.strip()

    return last_text


def clean_for_speech(text):
    """Make the text pleasant to hear: drop code, markdown noise, URLs,
    dashes, symbols, and emoji that TTS reads awkwardly."""
    text = re.sub(r"```.*?```", " code block omitted. ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    # [label](url) -> label, then bare URLs
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    # Markdown table separator rows, then pipes
    text = re.sub(r"^[\s|:\-]+$", "", text, flags=re.MULTILINE)
    text = text.replace("|", " ")
    # Bullets / headers / blockquotes at line start
    text = re.sub(r"^[#>\-\*\+•▪◦‣]+\s*", "", text, flags=re.MULTILINE)
    # Number ranges read as "to" (5-10, 5–10)
    text = re.sub(r"(?<=\d)\s*[–—-]\s*(?=\d)", " to ", text)
    # Em/en dashes, spaced hyphens, ellipses -> a natural comma pause
    text = re.sub(r"\s*[–—]+\s*", ", ", text)
    text = re.sub(r"\s-{1,3}\s", ", ", text)
    text = re.sub(r"\.{3,}|…", ". ", text)
    # Arrows read as "to"
    text = re.sub(r"\s*(?:->|=>|→|⇒|⟶)\s*", " to ", text)
    # Emphasis and leftover symbols TTS voices out loud
    text = re.sub(r"[\*~`#^<>=+\\{}\[\]\"]", "", text)
    text = text.replace("/", " ").replace("_", " ")
    # Emoji and other pictographs
    text = re.sub(
        r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
        r"✀-➿←-⇿⬀-⯿️‍✓✔✗✘]+",
        " ",
        text,
    )
    # Tidy punctuation runs left behind (", ," / ",." etc.) and whitespace
    text = re.sub(r"\s*,\s*(?=[,.;:!?])", "", text)
    text = re.sub(r"([,.;:!?])\1+", r"\1", text)
    text = re.sub(r"\s+([,.;:!?])(?=\s|$)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def pick_speech_source(text):
    """Return only the part of the reply meant to be spoken.

    Preferred: an explicit voice-summary line the assistant appends,
    marked with a speaker emoji, e.g. "🔊 All tests pass, sir."
    Fallback (model didn't write the marker): the whole reply, which
    speak-time truncation caps at max_chars — never a mid-thought cutoff
    after a few sentences.
    """
    # Only a line-START 🔊 counts as the marker (prose may mention 🔊
    # inline), and the real voice line is the LAST one in the message.
    matches = list(re.finditer(
        r"^\s*🔊\s*(?:voice summary\s*:?\s*)?",
        text, re.IGNORECASE | re.MULTILINE,
    ))
    if matches:
        rest = text[matches[-1].end():].split("\n\n", 1)[0].strip()
        if rest:
            return rest
    return text


def speak(text, cfg):
    # Preferred engine: Kokoro-82M via the local daemon. The stdlib-only
    # client starts the daemon if needed and falls back to `say` itself
    # if the daemon can't be reached.
    client = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "tts-client.py"
    )
    venv_py = os.path.expanduser("~/.claude/jarvis/venv/bin/python")
    engine = (os.environ.get("JARVIS_ENGINE") or cfg["engine"]).lower()
    use_daemon = (
        engine != "say"
        and os.path.exists(client)
        and os.path.exists(venv_py)
    )
    if use_daemon:
        cmd = [sys.executable or "python3", client, text]
    elif shutil.which("say"):
        say_voice = os.environ.get("JARVIS_VOICE") or cfg["say_voice"]
        cmd = ["say", "-v", say_voice]
        rate = os.environ.get("JARVIS_RATE")
        if rate:
            cmd += ["-r", rate]
        cmd.append(text)
    else:
        return
    # Detach so the hook returns immediately and audio plays in the background.
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def debug_log(msg):
    try:
        with open(os.path.join(JARVIS_DIR, "hook.log"), "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def main():
    if not armed():
        sys.exit(0)

    data = read_hook_input()
    tp = data.get("transcript_path", "")
    raw = get_last_assistant_text(tp)
    debug_log(f"fired: transcript={tp!r} exists={os.path.exists(tp)} raw_len={len(raw)}")
    text = clean_for_speech(pick_speech_source(raw))
    debug_log(f"speaking: {text[:120]!r}")
    if not text:
        sys.exit(0)

    cfg = load_config()
    max_chars = int(os.environ.get("JARVIS_MAX_CHARS") or cfg["max_chars"])
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + ". Response truncated, sir."

    speak(text, cfg)
    sys.exit(0)  # never block Claude from finishing


if __name__ == "__main__":
    main()
