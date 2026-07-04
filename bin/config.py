"""Layered, per-session config for JARVIS. Stdlib-only (runs under any python3).

Install root is ``~/.jarvis/`` (override with ``JARVIS_HOME`` for testing).
Effective settings are merged with this precedence, highest first:

    environment  >  per-session override  >  global defaults file  >  built-in DEFAULTS

The merge is re-computed on every call, so edits to the JSON files apply to the
next reply without restarting the daemon.
"""

import json
import os
import re

JARVIS_HOME = os.path.expanduser(os.environ.get("JARVIS_HOME", "~/.jarvis"))
BIN_DIR = os.path.join(JARVIS_HOME, "bin")
MODELS_DIR = os.path.join(JARVIS_HOME, "models")
SESSIONS_DIR = os.path.join(JARVIS_HOME, "sessions")
ARMED_DIR = os.path.join(JARVIS_HOME, "armed")
CONFIG_PATH = os.path.join(JARVIS_HOME, "config.json")

DEFAULTS = {
    "engine": "kokoro",      # "kokoro" (daemon) or "say" (system fallback)
    "voice": "bm_george",    # kokoro voice name
    "speed": 1.0,            # kokoro speech-speed multiplier
    "say_voice": "Daniel",   # system-TTS fallback voice
    "max_chars": 1200,       # truncate spoken text beyond this
}

# env var -> config key. Env always wins (per-run override).
_ENV_KEYS = {
    "JARVIS_ENGINE": "engine",
    "JARVIS_KOKORO_VOICE": "voice",
    "JARVIS_KOKORO_SPEED": "speed",
    "JARVIS_VOICE": "say_voice",
    "JARVIS_MAX_CHARS": "max_chars",
}

_CASTS = {"speed": float, "max_chars": int}


def ensure_dirs():
    """Create the ~/.jarvis/ subdirectories. Idempotent."""
    for d in (BIN_DIR, MODELS_DIR, SESSIONS_DIR, ARMED_DIR):
        os.makedirs(d, exist_ok=True)


def sanitize_session_id(session_id):
    """Make a session id safe to use as a filename."""
    if not session_id:
        return ""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id))


def session_config_path(session_id):
    return os.path.join(SESSIONS_DIR, f"{sanitize_session_id(session_id)}.json")


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _cast(cfg):
    for key, caster in _CASTS.items():
        if key in cfg:
            try:
                cfg[key] = caster(cfg[key])
            except (TypeError, ValueError):
                cfg[key] = DEFAULTS[key]
    return cfg


def load_config(session_id=None):
    """Return the effective config for a session (or global if session_id is None)."""
    cfg = dict(DEFAULTS)
    cfg.update(_read_json(CONFIG_PATH))                 # global defaults file
    if session_id:
        cfg.update(_read_json(session_config_path(session_id)))  # per-session
    for env, key in _ENV_KEYS.items():                  # environment wins
        val = os.environ.get(env)
        if val is not None and val != "":
            cfg[key] = val
    return _cast(cfg)


def set_session_value(session_id, key, value):
    """Write one per-session override key and return the updated override dict."""
    ensure_dirs()
    path = session_config_path(session_id)
    data = _read_json(path)
    data[key] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    return data
