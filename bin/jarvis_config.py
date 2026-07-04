"""Shared config loader for the JARVIS TTS scripts.

Settings live in ~/.claude/jarvis/config.json and are re-read on every
spoken reply, so edits (e.g. via /jarvis voice ...) apply immediately
without restarting the daemon.
"""

import json
import os

JARVIS_DIR = os.path.expanduser("~/.claude/jarvis")
CONFIG_PATH = os.path.join(JARVIS_DIR, "config.json")

DEFAULTS = {
    "engine": "kokoro",      # "kokoro" or "say"
    "voice": "bm_george",    # kokoro voice name
    "speed": 1.0,            # kokoro speech speed multiplier
    "say_voice": "Daniel",   # macOS say fallback voice
    "max_chars": 1200,       # truncate spoken text beyond this
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update(data)
    except Exception:
        pass
    return cfg
