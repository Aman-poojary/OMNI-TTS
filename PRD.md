# PRD — JARVIS: Provider-Agnostic, Cross-Platform, Packaged

> Source of truth: [plan.md](plan.md) (locked decisions) and [CONTEXT.md](CONTEXT.md)
> (current implementation). This PRD turns that plan into buildable tasks. Each
> task states its **Goal**, the **Context** a coder needs, and the concrete
> **Expectations** (deliverables + acceptance). Build tasks in order — later
> tasks depend on earlier ones.

---

## Problem Statement

Today `claude-jarvis` is a **macOS-only, Claude-Code-only** voice layer. It only
runs on Darwin (`afplay` / `say` are hardcoded, `install.sh` refuses other OSes),
it only integrates with Claude Code, and arming is **global** — two concurrent
sessions share one on/off state and one voice. A user on Windows/Linux, a user of
Codex, or a user running two sessions at once cannot use it well or at all.

## Solution

One **provider-neutral, OS-neutral core** installed at `~/.jarvis/`, with thin
per-provider adapters (Claude Code + Codex) that only register hooks and drop in
skills. Arming and config become **per-session**. A single shared stateless
daemon serves all sessions of both providers, plays audio **in-process** via
`sounddevice` (no player-binary dependency), streams synthesis for low latency,
and falls back to per-OS system TTS when the model is unavailable. Install is
`git clone` + `python install.py` on all three OSes.

## User Stories

1. As a Windows user, I want JARVIS to install and speak replies, so that I'm not blocked by macOS-only binaries.
2. As a Linux user, I want JARVIS to play audio without `afplay`, so that it works on my machine.
3. As a Codex user, I want the same voice layer as Claude Code users, so that my tool choice doesn't cost me the feature.
4. As a user running two sessions, I want to arm voice in one session only, so that the other session stays silent.
5. As a user running two sessions, I want each session to use its own voice, so that I can tell by ear which session is talking.
6. As a user, I want to change voice/speed for just my session, so that I don't disturb a global default others rely on.
7. As a user, I want the first spoken reply to start quickly, so that I'm not waiting through seconds of model-load silence.
8. As a user, I want a long reply to start speaking after the first sentence, so that I don't sit in silence while the whole reply renders.
9. As a user on AirPods, I want smooth audio, so that Bluetooth playback isn't choppy or garbled.
10. As a user, I want to cut off a long or wrong spoken reply instantly, so that I don't have to wait for it to finish or disarm voice entirely.
11. As a user whose model download failed, I want a system-voice fallback, so that I still hear replies instead of silence.
12. As a user, I want ending a Claude session to clean up its arming/config files, so that stale state doesn't accumulate.
13. As a Codex user (no session-end event), I want stale files swept automatically, so that cleanup still happens.
14. As a user resuming an old session, I want my provider transcripts untouched, so that history stays safe.
15. As an installer, I want `python install.py` to auto-detect my providers, so that I don't hand-configure anything.
16. As an installer, I want to uninstall cleanly, so that hooks are unregistered and `~/.jarvis/` is removed.
17. As a maintainer, I want one core and thin adapters, so that adding a provider doesn't fork the logic.

## Task Breakdown

Each task below is self-contained. Definition of done for the whole PRD is the
Verification checklist at the bottom.

---

### Task 1 — Relocate core to `~/.jarvis/` + layered config

**Goal:** Establish the provider-neutral install root and a per-session config
system that everything else builds on. (plan.md decisions 2, 5)

**Context:** Today core scripts live in `~/.claude/jarvis/bin/` and config is a
single global `~/.claude/jarvis/config.json` read by `bin/jarvis_config.py` over
built-in `DEFAULTS` (`engine`, `voice`, `speed`, `say_voice`, `max_chars`). Env
vars override per run. The new root is `~/.jarvis/` with subdirs
`bin/ models/ sessions/ armed/`. Providers get only *pointers* into this root.

**Expectations:**
- New layout created/used: `~/.jarvis/{bin,models,sessions,armed}`.
- `config.py` implements layered merge with precedence **env > session override >
  global default > built-in defaults**:
  - `~/.jarvis/config.json` = global defaults.
  - `~/.jarvis/sessions/<session_id>.json` = per-session overrides.
- A `load_config(session_id)` returns the effective config for a session; re-read
  on every reply (no daemon restart needed to pick up edits).
- Built-in defaults preserved from current behavior (`voice=bm_george`,
  `speed=1.0`, `say_voice=Daniel`, `max_chars=1200`, `engine`).

---

### Task 2 — Per-session arming

**Goal:** Replace global arming with per-session flag files so one session can be
armed without affecting another. (plan.md decision 4)

**Context:** Today arming is global via `speak_on` / `speak_once` files in
`~/.claude/jarvis/`. `remind.py` (UserPromptSubmit) and `speak.py` (Stop) both
check these. Both Claude and Codex supply `session_id` in the hook payload.

**Expectations:**
- Arming writes `~/.jarvis/armed/<session_id>` (persistent) and a one-shot
  variant for `/jarvis` (speak next reply then consume).
- `speak.py` speaks only if *its* payload's `session_id` is armed; consumes the
  one-shot flag after speaking.
- `remind.py` injects the 🔊 instruction only if that session is armed.
- Disarming removes that session's flag(s) only — never other sessions'.

---

### Task 3 — Stateless daemon: per-request voice/speed + in-process playback + resampling

**Goal:** Make the daemon a stateless renderer so different sessions can use
different voices, and remove the temp-WAV/`afplay` playback path. (plan.md
decisions 6, 8, 19)

**Context:** Today `bin/tts-daemon.py` bakes voice/speed in at start from config/
env, and `speak()` renders all chunks, concatenates, writes ONE temp WAV, plays
with `afplay`, deletes it. It keeps a single FIFO worker thread and idle-exits
after `JARVIS_TTS_IDLE_EXIT` (default 1800s). One loaded Kokoro model serves all
voices (voices are embeddings in `voices-v1.0.bin`). A working in-process +
resampling reference exists in `jarvis-v3/jarvis/speaker.py::render` (renders to a
numpy float32 array, resamples to device rate, `sd.play` + `sd.wait`).

**Expectations:**
- `/speak` request body carries `{text, voice, speed}`; the daemon no longer
  holds voice/speed globally. `speak.py`/`tts-client.py` compute the effective
  config (Task 1) and send it per request.
- Playback is in-process via `sounddevice` on the numpy waveform — **no temp WAV,
  no `afplay`**.
- **Device-rate resampling** before playback: query the output device's
  `default_samplerate`; if it differs from the model rate (24 kHz), resample with
  `scipy.signal.resample_poly` (ratio reduced by gcd). Same-rate is a no-op
  passthrough. Fixes choppy Bluetooth/AirPods audio.
- Single-worker FIFO ordering and idle self-exit preserved.

---

### Task 4 — Low-latency synthesis: streaming, small first chunk, background warmup, thread tuning

**Goal:** Cut time-to-first-audio and overall synthesis latency. (plan.md
decisions 14, 15, 16, 18)

**Context:** Today the daemon renders the *whole* reply before any audio plays
(multi-second silence on long replies), loads the model **lazily under a lock on
first `/speak`**, and runs onnxruntime at the library default of 1 intra-op
thread. `chunk_text` splits into ~280-char sentence groups.

**Expectations:**
- **Streaming pipeline:** producer/consumer — synthesize chunk N, hand to a
  playback consumer, synthesize chunk N+1 while N plays (feed numpy chunks to a
  `sounddevice` output stream). Never stall mid-reply; if the producer falls
  behind, resume on sentence boundaries.
- **Small first chunk:** `chunk_text` emits the first chunk as a single sentence;
  later chunks stay large.
- **Background warmup:** load the model on a startup thread when the daemon boots
  (not lazily under the lock). Keep a `/warmup` endpoint for an arm-time ping
  (`/jarvis-on` and `/jarvis` ping it). Optionally synthesize a throwaway
  one-word utterance to warm the ONNX graph.
- **Thread tuning:** set onnxruntime intra-op threads (≈ physical core count) at
  model load, via session options or `OMP_NUM_THREADS`. Benchmark to pick the
  default.

---

### Task 5 — Stop / barge-in

**Goal:** Let the user cut off the current spoken reply instantly without
disarming voice mode. (plan.md decision 17)

**Context:** Today `/jarvis-off` used a blanket `pkill afplay`. With in-process
playback (Task 3) there is no `afplay` process to kill. Independent of Task 3's
migration in principle, but here it targets the `sounddevice` path.

**Expectations:**
- Daemon `/stop` (POST) endpoint that (a) drains the pending `_jobs` queue and
  (b) aborts the currently playing utterance, plus an interrupt flag the worker
  checks between chunks.
- Exposed as a `jarvis stop` CLI command (Task 8) and a `/jarvis-stop` skill.
- `/jarvis-off` also calls stop (replaces `pkill afplay`).
- Default policy for a *new* request arriving mid-playback stays **FIFO** (queue,
  don't auto-interrupt).

---

### Task 6 — Per-OS system-TTS fallback

**Goal:** Guarantee an audible voice when Kokoro is unavailable. (plan.md
decision 13)

**Context:** Today the only fallback is macOS `say`. `tts-client.py` falls back to
`say` if the daemon is unreachable.

**Expectations:**
- Runtime-selected per-OS fallback: macOS `say`, Windows SAPI (PowerShell
  `System.Speech`), Linux `espeak`/`spd-say`.
- Used when the model/daemon path fails; a broken model produces a voice, not
  silence.

---

### Task 7 — `jarvis` CLI

**Goal:** Provide an OS-neutral command surface so skills contain no shell logic.
(plan.md decisions, "Adapters" + "Still to plan")

**Context:** Today skills embed shell (`touch`/`rm`/`lsof`/`open -t`/`pkill`).
That is not portable to Windows and couples skills to macOS. The exact CLI
surface is still open in plan.md — propose and lock it in this task.

**Expectations:**
- A `jarvis` CLI with at least: `arm-once`, `arm`, `disarm`, `stop`,
  `config ...` (and `status`, `say` for testing are welcome).
- Each subcommand operates on `~/.jarvis/` files and/or the daemon (arm writes
  session flag + pings `/warmup`; stop POSTs `/stop`; config reads/writes
  session override JSON).
- No OS-specific shell assumptions in the CLI itself.

---

### Task 8 — Provider adapters (Claude Code + Codex)

**Goal:** Register hooks and place skills per provider, pointing at the shared
core. (plan.md decisions 1, 3; "Adapters" section)

**Context:** Both providers expose `UserPromptSubmit` (with `additionalContext`
injection) and `Stop` hooks fed JSON on stdin, and both read `SKILL.md` files.
Only *registration location*, *hook payload schema*, and *session-end
availability* differ. Claude registers in `~/.claude/settings.json` (JSON); Codex
in `~/.codex/config.toml` or `~/.codex/hooks.json` (TOML/JSON). `SessionEnd` is
Claude-only.

**Expectations:**
- `adapters/claude/` merges hooks into `~/.claude/settings.json`; `adapters/codex/`
  into the Codex config. Register `UserPromptSubmit` + `Stop` on both;
  `SessionEnd` on Claude only.
- Hook command form is a bare `python`/`python3 <entry>` call with **no shell
  logic** (Windows/shell portability).
- Skills (`jarvis`, `jarvis-on`, `jarvis-off`, `jarvis-config`, `jarvis-stop`)
  reuse the same `SKILL.md` bodies but call the `jarvis` CLI (Task 7) instead of
  embedded shell. Handle Codex's optional `openai.yaml` sidecar if needed.
- **`speak.py` payload shim:** locate the assistant text/transcript per provider.
  Claude `transcript_path` is known; verify Codex's `Stop` payload and derive the
  spoken text accordingly (see "Open items").

---

### Task 9 — Cross-platform installer + uninstaller + model download

**Goal:** One clone-and-run install story identical on macOS/Windows/Linux.
(plan.md decisions 10, 11, 12)

**Context:** Today `install.sh` is bash and hard-exits on non-Darwin; it uses `uv`
to build a py3.11 venv and `curl`s the ~340 MB model. The daemon runs under the
venv; hook/client scripts are stdlib-only.

**Expectations:**
- `install.py` with `--provider claude|codex|all` (auto-detect installed
  providers by default). Steps: create `~/.jarvis/{bin,models,sessions,armed}`;
  build a Python env with stdlib `venv`+`pip` (use `uv` opportunistically if
  present, no hard dependency); download the model from GitHub releases into
  `~/.jarvis/models/`; register hooks per provider; place skills per provider.
- `uninstall.py` mirrors it: unregister hooks, remove `~/.jarvis/`, remove skill
  dirs.
- Both idempotent. On Linux, detect missing `libportaudio2` and warn with the
  install hint.

---

### Task 10 — Session cleanup (SessionEnd hook + age sweep)

**Goal:** Remove stale per-session files without ever touching provider history.
(plan.md decision 7)

**Context:** Per-session files live in `~/.jarvis/armed/` and
`~/.jarvis/sessions/`. Codex has no session-end event; sessions can also crash.

**Expectations:**
- Claude `SessionEnd` hook deletes that session's `armed/` + `sessions/` files.
- A **6-hour age-based sweep** (daemon tick / next `SessionStart`) as the
  universal backstop covering Codex and crashed sessions.
- Cleanup touches **only `~/.jarvis/` files**. Provider transcripts
  (`~/.claude/projects/**.jsonl`, `~/.codex/**`) are read-only and never deleted.

---

## Implementation Decisions

- **One core, thin adapters.** All logic lives under `~/.jarvis/`; adapters only
  register hooks and place skills.
- **Stateless daemon.** Voice/speed ride in each `/speak` request; one loaded
  Kokoro model serves all voices. Single-worker FIFO across all sessions of both
  providers on port 7739.
- **In-process audio.** `sounddevice` plays numpy waveforms; no temp WAV, no
  player binary. Device-rate resampling via `scipy.signal.resample_poly`.
- **Streaming producer/consumer** synthesis with a small first chunk; background
  model warmup at daemon boot; onnxruntime intra-op threads ≈ core count.
- **Per-session arming and config**, layered precedence env > session > global >
  built-in.
- **Config re-read every reply** — edits apply without restarting the daemon.
- **Skills call the `jarvis` CLI**, never embedded shell — the portability seam.
- **Hook commands** are bare `python`/`python3 <entry>` calls, no shell logic.
- **Fallback TTS** selected per-OS at runtime (`say` / SAPI / `espeak`).
- **Cleanup is `~/.jarvis/`-only**; provider transcripts are read-only.
- **Model backend stays `kokoro-onnx` (CPU)** for cross-platform reach. The MLX
  (Metal) backend from `jarvis-v3` is faster but Apple-Silicon-only and is **not
  adopted** — see Out of Scope.

## Testing Decisions

Good tests assert **external behavior** at the highest stable seam, not internal
implementation. Prefer existing seams. Proposed seams:

- **Config layering** — unit test `load_config(session_id)` precedence: built-in
  < global < session override < env. Pure function, easy seam.
- **Text cleaning** — assert `clean_for_speech` output is unchanged from current
  behavior (regression guard). Keep the current, more-thorough cleaner.
- **Payload shim** — feed captured Claude and Codex `Stop`/`UserPromptSubmit`
  sample payloads and assert the correct assistant text / `session_id` is
  extracted. This is the key cross-provider seam.
- **Chunking** — `chunk_text` emits a single-sentence first chunk, large later
  chunks, and handles run-on sentences.
- **Per-OS smoke** — `sounddevice` plays Kokoro output on macOS/Windows/Linux.
- **Resampling** — 48 kHz output device path is smooth; same-rate path is a no-op.
- **Streaming latency** — on a ~1200-char reply, first audio starts after ~one
  sentence, no audible stall between chunks.
- **Warmup** — first spoken reply after daemon start has no model-load delay.
- **Stop** — mid-playback `/jarvis-stop` (and `jarvis stop`) cuts audio and clears
  the queue while staying armed; `/jarvis-off` also stops.
- **End-to-end per provider** — install with `--provider`, arm one session, ask a
  question, confirm the 🔊 line is spoken; second session arms independently; run
  both providers and confirm shared-daemon FIFO.
- **Cleanup** — exiting a Claude session removes its `armed/`+`sessions/` files;
  a swept Codex session's files are removed; provider transcripts untouched.

Prior art: the current `bin/*.py` scripts are stdlib-only and already structured
as small functions (`chunk_text`, `clean_for_speech`, `load_config`) that are
directly unit-testable.

## Out of Scope

- **MLX / Metal TTS backend** (`jarvis-v3`'s `mlx-audio`). Faster but
  Apple-Silicon-only — conflicts with the cross-platform goal. Revisit only if we
  drop Windows/Linux support.
- **jarvis-v3's input/listening pipeline** (mic, STT, VAD, transcript polishing).
  Only the output/TTS path is harvested.
- **Acknowledgment-phrase cache** ("Okay.", "One moment." filler). Tied to
  interactive listening, not the Stop-hook model.
- **Antigravity provider** (plan.md decision 1).
- **A publish pipeline** — install is `git clone` + `python install.py` only.
- **Auto-barge-in** (a new request auto-interrupting current playback). Manual
  `/stop` only; new requests queue FIFO.

## Open Items (verify during implementation, not blocking)

- **Codex `Stop` payload** — does it include a transcript path / assistant text
  like Claude's? Drives the `speak.py` shim. If not, derive spoken text another
  way (Codex `Stop` fields or a session-local last-message cache).
- **Windows hook execution** — confirm how Claude Code / Codex run hook `command`
  strings on Windows (git-bash vs cmd/powershell); this is why the command must
  be a bare `python`/`python3 <entry>` call.
- **`sounddevice` on Linux** — may need `libportaudio2`; installer detects and
  warns.
- **Migration** — path for existing installs under `~/.claude/jarvis/` →
  `~/.jarvis/`.
- **`jarvis` CLI surface** — exact subcommands/args to lock in Task 7.
