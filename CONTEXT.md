# CONTEXT — claude-jarvis

> Orientation doc for humans and agents. Read this before diving into files.
> Describes the **current implementation**. `plan.md` is a *future* redesign that
> is NOT yet built — do not treat it as how the code works today.

## What this is

A JARVIS-style voice layer for **Claude Code on macOS**. When "armed", the
assistant's reply is spoken aloud in a British-male TTS voice (Kokoro-82M),
Iron-Man-style. Off by default; zero effect on normal sessions.

**macOS-only today**: playback uses `afplay`, fallback uses `say`, and
`install.sh` hard-exits on non-Darwin.

## Install layout

`install.sh` copies things out of this repo into the user's Claude config:

| Repo source        | Installed to                     |
|--------------------|----------------------------------|
| `bin/*.py`         | `~/.claude/jarvis/bin/`          |
| `skills/*/SKILL.md`| `~/.claude/skills/<name>/`       |
| `config.default.json` | `~/.claude/jarvis/config.json` (if absent) |
| model files        | `~/.claude/jarvis/models/` (downloaded, ~340 MB) |
| Python venv        | `~/.claude/jarvis/venv/` (uv, py3.11) |

Two hooks are registered in `~/.claude/settings.json`, both guarded with
`[ -f "$f" ] && python3 "$f" || true` so a missing script can never block prompts:
- `UserPromptSubmit` → `bin/remind.py`
- `Stop` → `bin/speak.py`

## The scripts (`bin/`)

| File | Runtime | Role |
|------|---------|------|
| `remind.py` | any python3 (stdlib) | `UserPromptSubmit` hook. If armed, injects ~600-char (~130-token) `additionalContext` telling Claude to end its reply with a `🔊`-prefixed JARVIS-voice paragraph. Silent when disarmed. |
| `speak.py` | any python3 (stdlib) | `Stop` hook. The orchestrator — see flow below. Detaches the speaker and always exits 0 (never blocks Claude). |
| `tts-client.py` | any python3 (stdlib) | Ensures the daemon is up (starts it from the venv if needed, 60s health poll), POSTs `{"text":...}` to `/speak`. Falls back to macOS `say` if daemon unreachable. |
| `tts-daemon.py` | **venv python** (needs kokoro-onnx, soundfile) | Long-lived HTTP server on `127.0.0.1:7739`. Holds the warm model, generates + plays audio via a single FIFO worker thread. |
| `jarvis_config.py` | shared | Loads `config.json` over built-in `DEFAULTS`, re-read on every reply. |

## Arming = flag files

Arming is **global** (not per-session), via files in `~/.claude/jarvis/`:
- `speak_on`   — persistent: speak every reply (`/jarvis-on`; removed by `/jarvis-off`).
- `speak_once` — one-shot: speak the next reply, then `speak.py` deletes it (`/jarvis`).

The skills are thin wrappers: `/jarvis-on` = `touch speak_on`, `/jarvis-off` =
`rm -f speak_on speak_once`, `/jarvis` = `touch speak_once`. **No process starts
when you arm** — the daemon launches lazily on the first spoken reply.

## End-to-end flow

1. `/jarvis-on` → `touch ~/.claude/jarvis/speak_on`.
2. You send a message → `remind.py` sees the flag, injects the "write a 🔊 line" instruction.
3. Claude replies, ending with `🔊 <spoken answer>`.
4. Reply ends → `Stop` hook runs `speak.py`:
   - `armed()` — check flags (consume `speak_once`); exit if disarmed.
   - Read `transcript_path` from stdin JSON; `get_last_assistant_text()` parses the
     JSONL and returns the **last** assistant message's text.
   - `pick_speech_source()` — take the paragraph after the **last** line starting
     with `🔊`; if no marker, fall back to the whole reply.
   - `clean_for_speech()` — strip code/markdown/URLs/emoji, dashes→commas, arrows→"to".
   - Truncate at `max_chars` (default 1200) → append "Response truncated, sir."
   - Spawn `tts-client.py` **detached**; exit 0.
5. `tts-client.py` — ensure daemon (start if needed), POST text, else `say` fallback.
6. `tts-daemon.py` — `/speak` enqueues text (returns 202); single worker synthesizes + plays.

## Audio generation

In `tts-daemon.py:speak()`:
- Text is split into ~280-char sentence groups (`chunk_text`, `MAX_CHUNK_CHARS=280`).
- Each chunk → `model.create()` → an in-memory numpy waveform (NOT a file).
- **All waveforms are concatenated into ONE array, written to ONE temp WAV, played
  once with `afplay`, then deleted** in a `finally` block. So: N gen calls → 1 file →
  1 playback → removed. Chunking keeps each generation short; it does NOT create
  multiple files. Whole-then-play avoids mid-reply stalls (the cost: no audio starts
  until the whole summary is synthesized).

## Model & memory lifecycle

- Model: Kokoro-82M ONNX. Files: `kokoro-v1.0.onnx` (~310 MB) + `voices-v1.0.bin`
  (~26 MB) in `~/.claude/jarvis/models/`. One model serves all voices (voices are
  embeddings in the .bin).
- **Loaded lazily on the first `/speak`** (not at daemon start, not at arm time).
  First spoken reply has a few-seconds delay; then it stays warm → instant.
- **~1 GB RSS while warm** is expected: ONNX weights in memory + onnxruntime CPU
  arenas/thread pools + numpy + soundfile + interpreter — not the on-disk size.
- **Idle self-exit**: watchdog thread; if queue empty and no request for
  `JARVIS_TTS_IDLE_EXIT` (default 1800s = 30 min), `os._exit(0)` frees the RAM.
- `install.sh` kills whatever holds port 7739 on reinstall so new code takes effect.
- `/jarvis-off` only removes flags — it does NOT kill the daemon (it idles out).

## Config (`~/.claude/jarvis/config.json`)

Defaults in `jarvis_config.py`: `engine` (`kokoro`|`say`), `voice` (`bm_george`),
`speed` (1.0), `say_voice` (`Daniel`), `max_chars` (1200). Re-read every reply, so
edits apply without restarting the daemon. Env vars override per-run
(`JARVIS_ENGINE`, `JARVIS_VOICE`, `JARVIS_KOKORO_VOICE`, `JARVIS_KOKORO_SPEED`,
`JARVIS_RATE`, `JARVIS_MAX_CHARS`, `JARVIS_TTS_PORT`, `JARVIS_TTS_IDLE_EXIT`).

## Dependencies

Installed **only at install time** (never at runtime): a uv-created py3.11 venv with
`kokoro-onnx`, `soundfile`, `setuptools<81`; model files curl'd from the kokoro-onnx
GitHub release. Both steps are idempotent (skip if present). The daemon runs under
the venv; the three hook/client scripts are stdlib-only and run under any `python3`.

## Skills (`skills/`)

`jarvis` (one-shot), `jarvis-on` (persistent), `jarvis-off`, `jarvis-config`. Each is
a `SKILL.md` with YAML frontmatter (`name`/`description`) and steps that mostly
touch/remove flag files and instruct writing the `🔊` line.

## Gotchas

- macOS-only (afplay/say; installer refuses other OSes).
- Arming is global, so both concurrent sessions share on/off state.
- The `🔊` marker must be at the **start of a line** and is the **last** such line;
  prose mentioning 🔊 inline won't be mistaken for it.
- If Claude omits the 🔊 line, the whole reply is spoken (truncated at max_chars).
- `plan.md` = future redesign (`~/.jarvis/`, sounddevice, per-session arming,
  cross-platform, Codex support). Not implemented — don't cite it as current behavior.
