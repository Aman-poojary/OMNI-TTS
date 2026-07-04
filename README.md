# claude-jarvis 🔊

A local, JARVIS-style voice for [Claude Code](https://claude.com/claude-code)
on macOS. When armed, a Stop hook speaks Claude's replies aloud in a British
voice — generated fully offline by the
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) TTS model running on
your machine. No API keys, no cloud audio.

## How it works

```
you: /jarvis how many tests failed?
          │
          ▼
UserPromptSubmit hook (remind.py) ── tells the model to end its reply with a
          │                          spoken-style "🔊 ..." summary paragraph
          ▼
Claude answers, ending with:  🔊 Three failures, sir — all in the auth suite.
          │
          ▼
Stop hook (speak.py) ── extracts the 🔊 line, cleans it for speech
          │
          ▼
tts-client.py ── posts it to a warm local daemon (auto-started on port 7739)
          │
          ▼
tts-daemon.py ── Kokoro-82M generates audio, plays it as one continuous clip
```

- **Only speaks when armed** via flag files — normal sessions are untouched.
- **Model-agnostic** — works with any Claude model; the reminder hook injects
  the voice-summary instruction on every armed message. If a model forgets
  the 🔊 line, the whole reply is spoken (capped at `max_chars`).
- **Falls back to macOS `say`** automatically if the daemon can't be reached.
- **Daemon idles out** after 30 minutes and restarts on demand; nothing runs
  at boot.
- **Hooks can never block Claude** — commands are guarded with
  `[ -f "$f" ] && ... || true`, so even deleting the scripts just disables
  the voice instead of blocking your prompts.

## Requirements

- macOS (audio uses `afplay` / `say`)
- Claude Code
- `python3` on PATH (any recent version; the hooks are stdlib-only)
- [`uv`](https://docs.astral.sh/uv/) (used once, to build the daemon's venv)
- ~900 MB disk: ~340 MB model files + the venv

## Install

```bash
git clone https://github.com/YOURUSER/claude-jarvis.git
cd claude-jarvis
./install.sh
```

Then **restart Claude Code** (the slash-command menu only refreshes on
startup) and try:

```
/jarvis what does this repo do?
```

Re-running `install.sh` updates scripts and skills in place; the venv and
model downloads are skipped if present. Your existing config is kept.

## Commands

| Command | What it does |
|---|---|
| `/jarvis <question>` | Answer one question aloud (one-shot) |
| `/jarvis-on` | Speak every reply until turned off |
| `/jarvis-off` | Silence — also stops audio mid-playback if asked |
| `/jarvis-config` | Show/change voice settings, or open the config file |

## Configuration

Settings live in `~/.claude/jarvis/config.json` and are re-read on every
spoken reply — edits apply immediately, no restart:

| Key | Default | Meaning |
|---|---|---|
| `engine` | `kokoro` | `kokoro` (local model) or `say` (macOS built-in) |
| `voice` | `bm_george` | Kokoro voice: `bm_george`, `bm_lewis` (British), `am_michael`, `am_adam` (American), `af_heart`, `af_bella` (female), … |
| `speed` | `1.0` | Speech speed multiplier |
| `say_voice` | `Daniel` | Voice for the macOS `say` fallback |
| `max_chars` | `1200` | Truncate spoken text beyond this |

Env overrides per-run: `JARVIS_ENGINE`, `JARVIS_VOICE`, `JARVIS_RATE`,
`JARVIS_MAX_CHARS`, `JARVIS_KOKORO_VOICE`, `JARVIS_KOKORO_SPEED`,
`JARVIS_TTS_PORT`, `JARVIS_TTS_IDLE_EXIT`.

## What gets installed where

| Path | Contents |
|---|---|
| `~/.claude/jarvis/bin/` | `speak.py` (Stop hook), `remind.py` (UserPromptSubmit hook), `tts-client.py`, `tts-daemon.py`, `jarvis_config.py` |
| `~/.claude/jarvis/models/` | Kokoro model files (downloaded by the installer) |
| `~/.claude/jarvis/venv/` | Python 3.11 venv for the daemon |
| `~/.claude/jarvis/config.json` | Your settings |
| `~/.claude/skills/jarvis*/` | The four slash commands |
| `~/.claude/settings.json` | Two hook entries (merged in, nothing else touched) |

Flag files `~/.claude/jarvis/speak_once` / `speak_on` control arming;
`hook.log` and `daemon.log` in the same directory help with debugging.

## Uninstall

```bash
./uninstall.sh
```

Removes the hooks, skills, scripts, venv, and models.

## Credits

- TTS: [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via
  [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) (model files are
  downloaded from the kokoro-onnx release page)
