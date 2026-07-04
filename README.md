# jarvis 🔊

A local, JARVIS-style voice for [Claude Code](https://claude.com/claude-code)
**and Codex**, on **macOS, Windows, and Linux**. When armed, a Stop hook speaks
the assistant's replies aloud — generated fully offline by the
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) TTS model on your
machine. No API keys, no cloud audio.

## How it works

```
you: /jarvis how many tests failed?
          │
          ▼
UserPromptSubmit hook (remind.py) ── if THIS session is armed, tells the model
          │                          to end its reply with a "🔊 ..." paragraph
          ▼
assistant answers, ending with:  🔊 Three failures, sir — all in the auth suite.
          │
          ▼
Stop hook (speak.py) ── extracts the 🔊 line, cleans it, if the session is armed
          │
          ▼
tts_client.py ── posts {text, voice, speed} to a warm local daemon (port 7739)
          │
          ▼
tts_daemon.py ── Kokoro-82M streams audio, played in-process via sounddevice
```

- **Per-session arming** — arming one session never affects another; each
  session can even use a different voice.
- **Provider-neutral core** at `~/.jarvis/`; thin adapters register hooks and
  place skills for Claude Code and Codex.
- **In-process audio** via `sounddevice` (no `afplay`/player binary), resampled
  to your output device's rate so Bluetooth/AirPods playback isn't choppy.
- **Streaming synthesis** — the first sentence starts speaking while the rest
  renders, so long replies don't sit in silence.
- **Interrupt without disarming** — `/jarvis-stop` cuts off the current reply.
- **Per-OS fallback** — system TTS (`say` / SAPI / `espeak`) if the model is
  unavailable, so you still hear a voice.
- **Daemon idles out** after 30 minutes and restarts on demand; nothing runs at
  boot. Hooks always exit 0 — they can never block the assistant.

## Requirements

- macOS, Windows, or Linux (Linux needs `libportaudio2` for `sounddevice`)
- Claude Code and/or Codex
- `python3` on PATH (the hooks/CLI are stdlib-only)
- `uv` is used if present; otherwise the installer falls back to `venv` + `pip`
- ~900 MB disk: ~340 MB model files + the venv

## Install

```bash
git clone https://github.com/YOURUSER/jarvis.git
cd jarvis
python install.py            # auto-detects Claude Code / Codex
# or: python install.py --provider claude|codex|all
```

Then **restart your provider** (the slash-command menu refreshes on startup)
and try:

```
/jarvis what does this repo do?
```

Re-running `install.py` updates scripts and skills in place; the venv and model
downloads are skipped if present. Your existing config is kept.

## Commands

| Command | What it does |
|---|---|
| `/jarvis <question>` | Answer one question aloud (one-shot, this session) |
| `/jarvis-on` | Speak every reply in this session until turned off |
| `/jarvis-off` | Silence this session and stop any audio playing |
| `/jarvis-stop` | Cut off the current spoken reply, staying armed |
| `/jarvis-config` | Show/change per-session voice settings |

## Configuration

Settings are **layered**, highest precedence first:
**environment > per-session override > `~/.jarvis/config.json` (global) >
built-in defaults**. Edits apply on the next reply — no restart.

| Key | Default | Meaning |
|---|---|---|
| `engine` | `kokoro` | `kokoro` (local model) or `say` (system TTS) |
| `voice` | `bm_george` | Kokoro voice: `bm_george`, `bm_lewis` (British), `am_michael`, `am_adam` (American), `af_heart`, `af_bella` (female), … |
| `speed` | `1.0` | Speech speed multiplier |
| `say_voice` | `Daniel` | Voice for the system-TTS fallback |
| `max_chars` | `1200` | Truncate spoken text beyond this |

`/jarvis-config` writes the current session's override. Env overrides per run:
`JARVIS_ENGINE`, `JARVIS_KOKORO_VOICE`, `JARVIS_KOKORO_SPEED`, `JARVIS_VOICE`
(fallback voice), `JARVIS_MAX_CHARS`, `JARVIS_TTS_PORT`, `JARVIS_TTS_IDLE_EXIT`,
`JARVIS_TTS_THREADS`, `JARVIS_HOME`.

## What gets installed where

| Path | Contents |
|---|---|
| `~/.jarvis/bin/` | Core scripts (hooks, daemon, client, CLI, helpers) |
| `~/.jarvis/models/` | Kokoro model files (downloaded by the installer) |
| `~/.jarvis/venv/` | Python venv for the daemon |
| `~/.jarvis/config.json` | Global defaults |
| `~/.jarvis/sessions/<id>.json` | Per-session config overrides |
| `~/.jarvis/armed/<id>` | Per-session arming flags |
| `~/.claude/skills/jarvis*/` · `~/.codex/skills/jarvis*/` | The slash commands |
| `~/.claude/settings.json` · `~/.codex/hooks.json` | Hook entries (merged in) |

## Uninstall

```bash
python uninstall.py
```

Stops the daemon, unregisters hooks + removes skills for both providers, and
deletes `~/.jarvis/`. Your provider transcripts/history are never touched.

## Credits

- TTS: [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via
  [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx)
- Output-path ideas (device-rate resampling, in-process playback) adapted from
  the jarvis-v3 TTS pipeline.
