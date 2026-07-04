# CONTEXT — jarvis

> Orientation doc for humans and agents. Read this before diving into files.
> Describes the **current implementation** (the cross-platform, provider-neutral
> redesign built from [plan.md](plan.md) / [PRD.md](PRD.md)).

## What this is

A JARVIS-style voice layer for **Claude Code and Codex**, on **macOS, Windows,
and Linux**. When a session is "armed", the assistant's reply is spoken aloud by
Kokoro-82M running locally. Off by default; zero effect on unarmed sessions.

## Install layout (`~/.jarvis/`)

`install.py` builds a provider-neutral root and points providers at it:

| Repo source | Installed to |
|---|---|
| `bin/*.py` | `~/.jarvis/bin/` |
| `config.default.json` | `~/.jarvis/config.json` (if absent) |
| model files | `~/.jarvis/models/` (downloaded, ~340 MB) |
| Python venv | `~/.jarvis/venv/` (uv if present, else venv+pip) |
| `skills/*/SKILL.md` | `~/.claude/skills/<name>/` and/or `~/.codex/skills/<name>/` |

Per-session state also lives here: `~/.jarvis/sessions/<id>.json` (config
overrides), `~/.jarvis/armed/<id>` and `<id>.once` (arming), `last_session`
(CLI session resolution). Adapters register hooks: Claude →
`~/.claude/settings.json` (`UserPromptSubmit`, `Stop`, `SessionEnd`), Codex →
`~/.codex/hooks.json` (`SessionStart`, `UserPromptSubmit`, `Stop` — no
session-end). Hook commands are bare `python3 <entry>` calls, no shell logic.

## The scripts (`bin/`)

| File | Runtime | Role |
|---|---|---|
| `config.py` | stdlib | Layered config: env > session override > global file > built-in DEFAULTS. Paths for `~/.jarvis/`. Records/reads `last_session`. |
| `armed.py` | stdlib | Per-session arming flags (persistent + one-shot). |
| `payload.py` | stdlib | Provider payload shim: `session_id` + the current reply's text (Claude transcript, inline Codex fallback). Only accepts assistant text written after the newest user prompt and skips sidechain entries — returns `""` until the reply is flushed, so a Stop that races the transcript write never re-speaks the previous reply. |
| `textproc.py` | stdlib | `pick_speech_source`, `clean_for_speech`, `chunk_text` (small first chunk). |
| `remind.py` | stdlib | `UserPromptSubmit` hook. Records last session; if armed: injects the 🔊 instruction, refreshes flag mtimes (sweep protection), and barge-ins (session-scoped `/stop`). |
| `statusline.py` | stdlib | Claude `statusLine` segment: armed state, daemon warm/speaking, session-state presence. |
| `speak.py` | stdlib | `Stop` hook orchestrator. Speaks only if this session is armed; detaches the client; always exits 0. |
| `tts_client.py` | stdlib | Ensures the daemon (cross-platform venv), POSTs `{text,voice,speed}`, else per-OS fallback. |
| `tts_daemon.py` | **venv** | Stateless HTTP daemon on `127.0.0.1:7739`. Streams synth + playback; `/health`, `/speak`, `/warmup`, `/stop` (optionally session-scoped), `/status` (JSON), `/ui` (debug page). |
| `audio.py` | venv | `sounddevice` playback + device-rate resampling. |
| `fallback.py` | stdlib | Per-OS system TTS (say / SAPI / espeak). |
| `cli.py` | stdlib | The `jarvis` CLI skills call (`arm`/`disarm`/`stop`/`config`/…). |
| `cleanup.py` | stdlib | `cleanup_session` + 6-hour `sweep`. |
| `session_end.py` | stdlib | Claude `SessionEnd` hook → `cleanup_session`. |
| `session_sweep.py` | stdlib | Codex `SessionStart` hook → age-based `sweep`. |

## Arming = per-session flag files

`~/.jarvis/armed/<session_id>` (persistent, `/jarvis-on`) and `<session_id>.once`
(one-shot, `/jarvis`, consumed by `speak.py` after one reply). Skills call the
`jarvis` CLI, which resolves "this session" from `--session`, then
`CLAUDE_SESSION_ID`/`JARVIS_SESSION_ID`, then `last_session` (written by
`remind.py` when the prompt was submitted). Arming pings `/warmup`.

## End-to-end flow

1. `/jarvis-on` → `jarvis arm` writes `~/.jarvis/armed/<sid>` and pings `/warmup`.
2. You send a message → `remind.py` records the session and (if armed) injects
   the "write a 🔊 line" instruction.
3. Assistant replies, ending with `🔊 <spoken answer>`.
4. `Stop` → `speak.py`: `should_speak(session_id)` (consumes one-shot); read the
   current reply via the payload shim (tail-read — only the transcript's
   last 256 KB, so huge Desktop transcripts can't blow the hook timeout), polling
   up to 6 s **until the reply's 🔊 source is visible** — Stop can fire before
   the provider flushes the final line, and in multi-tool turns the mid-turn
   narration is already flushed, so "non-empty" is not proof the reply is current;
   `pick_speech_source` + `clean_for_speech`; truncate at `max_chars`; spawn
   `tts_client.py` detached.
5. `tts_client.py` — load the session's config, ensure the daemon, POST
   `{text, voice, speed}`; else per-OS fallback.
6. `tts_daemon.py` — enqueue; the FIFO worker streams synth→playback.

## Audio generation (`tts_daemon.py`)

Stateless: voice/speed/session ride in each `/speak`, so one loaded model serves
all sessions' voices. Jobs are tagged with their session id and wait in a
scannable deque; one FIFO worker plays them in order across sessions, and a new
`/speak` for a session **supersedes** that session's still-queued jobs so
back-to-back replies never pile up. `render_and_play` runs a producer/consumer:
a synth thread renders each `chunk_text` chunk (first chunk is one sentence)
and resamples it to the device rate; the worker writes chunks to a
`sounddevice` OutputStream as they arrive. First audio lands after one
sentence, not the whole reply. PortAudio snapshots the device list at init, so
before every job the daemon re-enumerates devices (`audio.reset()`) — a
default-output change (AirPods/USB) between jobs would otherwise open a stream
against a stale device (-9986) and drop the job silently. A failed open is
retried once with a fresh list, then falls back to the per-OS system TTS. Every job carries its own abort Event: `/stop`
with `{"session_id"}` kills only that session's queued + playing jobs (used by
`remind.py` barge-in and `jarvis disarm`); an empty `/stop` kills everything.
The daemon also keeps a rolling event feed (queued/superseded/play/stop/errors)
exposed at `/status` and rendered by the `/ui` debug page.

## Model & lifecycle

- Kokoro-82M ONNX (`kokoro-v1.0.onnx` + `voices-v1.0.bin` in `~/.jarvis/models/`).
- Warmed on a background thread at daemon boot; `/warmup` re-triggers at arm time.
- `OMP_NUM_THREADS` set to the core count before load (`JARVIS_TTS_THREADS`
  overrides) for faster CPU synthesis.
- ~1 GB RSS while warm. Idle self-exit after `JARVIS_TTS_IDLE_EXIT` (1800s).

## Config

`config.load_config(session_id)` merges built-in DEFAULTS ⊕ global
`~/.jarvis/config.json` ⊕ session override ⊕ env (env wins). Keys: `engine`,
`voice`, `speed`, `say_voice`, `max_chars`. Re-read every reply.

## Cleanup

Claude `SessionEnd` → `cleanup_session` removes that session's `armed/` +
`sessions/` files. Codex has no `SessionEnd`, so the daemon watchdog and Codex
`SessionStart` hook run the 6-hour `sweep` backstop for Codex and crashed
sessions. `remind.py` refreshes an armed session's flag mtimes on every prompt,
so the sweep never disarms a session that is still actively prompting. Only `~/.jarvis/` files are ever deleted — provider
transcripts/history are read-only.

## Gotchas

- Arming is **per-session**; the CLI resolves the session via `last_session`
  (written by the UserPromptSubmit hook from the same payload `session_id` the
  Stop hook uses), so a slash command run right after submitting the prompt
  targets the right session. `last_session` **must** win over `CLAUDE_SESSION_ID`
  / `JARVIS_SESSION_ID`: in the Claude Code CLI those env vars are a different id
  namespace than the hook payload `session_id`, so trusting them first armed a
  session the Stop hook never receives — the reply showed 🔊 but nothing played
  (works in Desktop only because there the env id happens to match).
- The `🔊` marker must start a line and be the **last** such line; otherwise the
  whole reply is spoken (truncated at `max_chars`).
- Linux needs `libportaudio2` for `sounddevice` (installer warns if missing).
- Codex's `Stop` payload shape is assumed; verify it feeds `payload.py` (see
  plan.md "To verify"). Adjust `adapters/codex/register.py` once confirmed.
