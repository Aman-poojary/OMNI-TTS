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

In Codex, skills are invoked as `$jarvis` or selected from `/skills`. The
installer also creates deprecated custom-prompt shims, so Codex's slash menu can
show `/prompts:jarvis`, `/prompts:jarvis-on`, etc. Codex does not expose custom
skills as plain `/jarvis` commands.

Re-running `install.py` updates scripts and skills in place; the venv and model
downloads are skipped if present. Your existing config is kept.

## Commands

| Command | What it does |
|---|---|
| `/jarvis <question>` (Claude) / `$jarvis <question>` or `/prompts:jarvis <question>` (Codex) | Answer one question aloud (one-shot, this session) |
| `/jarvis-on` (Claude) / `$jarvis-on` or `/prompts:jarvis-on` (Codex) | Speak every reply in this session until turned off |
| `/jarvis-off` (Claude) / `$jarvis-off` or `/prompts:jarvis-off` (Codex) | Silence this session and stop any audio playing |
| `/jarvis-stop` (Claude) / `$jarvis-stop` or `/prompts:jarvis-stop` (Codex) | Cut off the current spoken reply, staying armed |
| `/jarvis-config` (Claude) / `$jarvis-config` or `/prompts:jarvis-config` (Codex) | Show/change per-session voice settings |

### Context cost

The Claude Code skills are built to stay out of your context window:

- `jarvis-on/off/stop/config` set `disable-model-invocation: true`, so their
  descriptions are never loaded into the session's skill listing — only
  `/jarvis` (the one-shot) stays model-invocable for "say this aloud" asks.
- The side-effect commands (arm, disarm, stop, status) run as `` !`cmd` ``
  preprocessing inside the skill, so there is no Bash tool round-trip — a
  `/jarvis-on` costs a few hundred tokens instead of a couple of thousand.
- While voice mode is armed, a UserPromptSubmit hook injects a ~180-token
  reminder per message so any model writes the 🔊 line correctly.

### Zero-token control from the shell

The installer writes a `jarvis` shim into `~/.jarvis/bin/`. Add that directory
to your PATH (or alias it) and you can control the CURRENT session from any
terminal without spending a single context token:

```bash
jarvis on      # arm — spoken replies until disarmed   (alias for: arm)
jarvis arm | arm-once | disarm | stop | status
jarvis config voice am_michael
```

The CLI targets the session that most recently received a prompt (recorded by
the UserPromptSubmit hook), or pass `--session <id>` explicitly. The armed
session's replies speak correctly with no skill invocation at all, because the
per-message reminder hook carries the 🔊-line instructions.

## Status line + debug UI

The Claude Code status line can show JARVIS state per session:
`🔊 JARVIS on ⚡` (armed, daemon warm, `▶` appended while speaking) or
`🔇 JARVIS off · session –` (disarmed; `session –` means this session's state
files were cleaned or swept). The installer registers
`~/.jarvis/bin/statusline.py` as the `statusLine` command when none exists; if
you already have one, pipe the same stdin JSON through the script and append
its output as an extra segment.

For debugging, the daemon serves a live dashboard at
`http://127.0.0.1:7739/ui` (`jarvis ui` opens it): model/queue state, what is
being spoken for which session, session arming files on disk, a rolling event
feed (queued / superseded / play / stop / errors), and the hook + daemon log
tails. `GET /status` returns the same data as JSON.

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
| `~/.claude/skills/jarvis*/` · `~/.agents/skills/jarvis*/` | The Jarvis skills |
| `~/.codex/prompts/jarvis*.md` | Codex slash-menu shims (`/prompts:jarvis*`) |
| `~/.claude/settings.json` · `~/.codex/hooks.json` | Hook entries (merged in) |

Claude Code gets an exact `SessionEnd` cleanup hook. Codex does not expose a
session-end event, so JARVIS registers a `SessionStart` stale-file sweep and the
daemon also sweeps stale session files while warm.

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
