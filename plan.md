# JARVIS: Provider-Agnostic + Cross-Platform + Packaged

> Status: **planning** — decisions below are agreed; implementation deferred.
> There are still open areas to plan (see "Still to plan").

## Context

`claude-jarvis` today is a macOS-only, Claude-Code-only voice layer: a Kokoro
TTS daemon + Stop/UserPromptSubmit hooks + 4 skills, all installed under
`~/.claude/jarvis/` by a bash `install.sh`. The goal is to (1) make it work with
**Codex** as well as Claude Code, (2) run on **macOS, Windows, and Linux**, and
(3) **package** it cleanly given its Python + native-model dependencies.

Key finding from research: Codex's hook + skill systems have converged with
Claude Code's. Both expose `UserPromptSubmit` (with `additionalContext`
injection) and `Stop` (turn end) hooks fed JSON on stdin, and both read
`SKILL.md` files (YAML frontmatter `name`/`description`). So the core scripts are
~90% reusable across providers; only *registration location*, *hook payload
schema*, and *session-end availability* differ.

## Goals

- One provider-neutral core; thin per-provider adapters (Claude + Codex).
- Runs on macOS / Windows / Linux with no macOS-only binaries.
- A clean install/packaging story for a Python app that pulls a ~340 MB model.

---

## Locked decisions

1. **Providers:** Claude Code + Codex. Antigravity out of scope.
2. **Neutral install root:** core moves from `~/.claude/jarvis/` to **`~/.jarvis/`**.
   Providers only get *pointers* into it (hook registration + skill dirs).
3. **Both providers simultaneously:** yes — a single shared daemon serves all
   sessions of both providers over HTTP (port 7739). FIFO across everything falls
   out of the existing single-worker queue for free.
4. **Arming is per-session**, not global. `/jarvis-on` writes
   `~/.jarvis/armed/<session_id>`; each `Stop` hook speaks only if *its*
   `session_id` is armed. Both providers supply `session_id` in the hook payload.
5. **Config is per-session**, layered:
   - `~/.jarvis/config.json` = global defaults.
   - `~/.jarvis/sessions/<session_id>.json` = per-session overrides (`/jarvis-config`).
   - Precedence: **env > session override > global default > built-in defaults**.
6. **Daemon becomes stateless renderer.** Voice/speed no longer baked in at
   daemon start; they **ride in each `/speak` request**. `speak.py` merges the
   effective config and sends `{text, voice, speed}`. One loaded Kokoro model
   serves all voices (voices are embeddings in `voices-v1.0.bin`).
   - Bonus: different sessions can use different voices → audible "who's talking".
7. **Session cleanup = hybrid:** register Claude's `SessionEnd` hook to delete
   that session's `armed/` + `sessions/` files on exit; plus a **6-hour
   age-based sweep** (daemon tick / next `SessionStart`) as the universal
   backstop (covers Codex, which has no session-end event, and crashed sessions).
   - Cleanup touches **only `~/.jarvis/` files**. Provider transcripts/history
     (`~/.claude/projects/**.jsonl`, `~/.codex/**`) are read-only to JARVIS and
     never deleted — resuming old sessions stays safe.
8. **Audio playback is in-process via `sounddevice`** (PortAudio). The daemon
   plays the Kokoro numpy waveform directly — **no temp WAV, no `afplay`/`aplay`/
   `paplay`**. Removes the whole "is a player binary installed" class of bugs.
   jarvis-v3 `jarvis/speaker.py` (`render` → `sd.play(audio, samplerate=...)` →
   `sd.wait()`) is a working reference for this path; keep the current `afplay`
   route as a fallback when `sounddevice`/PortAudio is unavailable.
9. **Warmup at arm time:** `/jarvis-on` (and `/jarvis`) ping the daemon to
   preload the model so the first spoken reply isn't delayed by model load.
10. **Packaging:** git clone + `python install.py --provider claude|codex|all`
    (auto-detect by default). No publish pipeline; identical on all 3 OSes.
11. **Python env:** stdlib `venv` + `pip`, opportunistically use `uv` if already
    present. No hard `uv` dependency.
12. **Model delivery:** download on install from GitHub releases (current source),
    into `~/.jarvis/models/`. Keeps repo small; needs network at install time.
13. **Fallback:** per-OS system TTS when Kokoro is unavailable — macOS `say`,
    Windows SAPI (PowerShell `System.Speech`), Linux `espeak`/`spd-say`. So a
    broken model still produces an audible voice rather than silence.
14. **Streaming synthesis + playback (low time-to-first-audio).** Today the
    daemon synthesizes *every* chunk, concatenates, writes one WAV, then plays —
    so nothing is heard until the whole reply is rendered (multi-second silence
    on long replies). Change the daemon worker to a producer/consumer pipeline:
    synthesize chunk N, hand it to a playback consumer, synthesize chunk N+1
    while N plays. Time-to-first-audio drops from "render the whole reply" to
    "render the first chunk." The producer stays ahead of the consumer, so the
    existing "never stall mid-reply" guarantee holds; if it ever falls behind,
    chunks resume on natural sentence boundaries where a brief pause is
    unobtrusive. Pairs with `sounddevice` (decision 8): feed numpy chunks
    straight to an output stream — no temp files.
15. **Small first chunk.** `chunk_text` emits the first chunk as a single
    sentence (not a full ~280-char group); later chunks stay large. First audio
    then lands after one sentence of synthesis. Cheap tweak; compounds with
    decision 14.
16. **Background warmup at daemon startup.** Load the Kokoro model in a
    background thread the moment the daemon boots, so it is warm before the first
    `/speak`. The current lazy load holds `_model_lock` and blocks the first real
    reply even though `/health` already returns OK. This complements decision 9
    (arm-time ping): the ping starts the daemon; the background thread warms the
    model without blocking anything. Optionally synthesize a throwaway one-word
    utterance to warm the ONNX graph.
17. **Stop / barge-in.** Add a `/stop` endpoint (POST) to the daemon that
    (a) drains the pending `_jobs` queue and (b) aborts the currently playing
    utterance, plus an interrupt flag the worker checks between chunks. Exposed
    as a `jarvis stop` CLI command and a `/jarvis-stop` skill so a user can cut
    off a long or wrong reply immediately **without disarming** voice mode.
    `/jarvis-off` also calls stop — a cleaner replacement for the old blanket
    `pkill afplay`.
    - **Independent of decision 8.** Stop does *not* require the in-process
      `sounddevice` migration: the daemon can hold the current player `Popen`
      (today `afplay`) and `.terminate()` it on `/stop` — the pattern
      jarvis-plugin uses (SIGTERM the `play` subprocess + mark interrupted). Once
      playback moves in-process, this becomes a `sounddevice` stop instead. So
      decision 17 can ship on the current architecture, ahead of decision 8.
    - This settles the *interrupt* case of barge-in; whether a *new* request
      arriving mid-playback interrupts or queues stays FIFO by default (see
      "Still to plan").
18. **onnxruntime thread tuning.** Kokoro runs on CPU onnxruntime; synthesis
    speed scales with the intra-op thread count. Set a sane default (≈ physical
    core count) via onnxruntime session options or `OMP_NUM_THREADS` when the
    daemon loads the model, instead of the library default of 1. jarvis-plugin
    does this explicitly (`numThreads: 2` for Kokoro). Cheap per-chunk speedup
    that compounds with streaming (decision 14) — benchmark to pick the default.
19. **Device-rate resampling (from jarvis-v3).** Kokoro renders at a fixed native
    rate (24 kHz); most output devices run at 48 kHz, and Bluetooth/AirPods in
    particular produce choppy/garbled audio when fed a mismatched rate. Before
    playback, resample the numpy waveform from the model rate to the output
    device's `default_samplerate` via `scipy.signal.resample_poly` (poly ratio =
    `device_rate / model_rate` reduced by gcd). Backend-independent — applies to
    the current ONNX path, not just MLX. This pairs with decision 8 (in-process
    `sounddevice`): query the output device rate, resample, feed the stream. Port
    the working implementation from jarvis-v3 `jarvis/speaker.py::render`.

---

## Harvest from jarvis-v3 (output path only)

`jarvis-v3` is a separate local voice repo (mic → STT → Claude → TTS). We only
mine its **output** (TTS) path — its input/listening pipeline is out of scope.
Its output lives in one synchronous library file, `jarvis/speaker.py`, not a
daemon, so we port *rendering logic* into our daemon rather than dropping files
in wholesale. Findings:

- **Take — device-rate resampling.** See decision 19. Best portable win; fixes
  Bluetooth/AirPods audio and is backend-independent.
- **Take — in-process `sounddevice` playback.** Already decision 8; jarvis-v3's
  `render`/`sd.play` is the working reference.
- **Tradeoff — MLX Kokoro backend (`mlx-audio`).** jarvis-v3 renders Kokoro on
  Metal (GPU) instead of our `kokoro-onnx` (CPU) — faster synthesis. But it is
  **Apple-Silicon-only**, which conflicts with the cross-platform goal
  (decisions 1–2, macOS/Windows/Linux). Adopt only if we abandon cross-platform;
  otherwise keep ONNX and lean on thread tuning (decision 18) + streaming
  (decision 14) for speed. Not adopted for now.
- **Skip — acknowledgment-phrase cache** ("Okay.", "One moment." pre-rendered
  filler). Tied to the interactive listening loop (play filler while thinking);
  doesn't fit our Stop-hook "speak the final answer" model.
- **Skip — `sanitize_for_tts` regex table.** Our `speak.py::clean_for_speech` is
  already more thorough (handles emoji, number ranges like "5-10"→"5 to 10",
  arrows, and `[label](url)` link stripping that jarvis-v3 omits). No change.

## Component changes (target design)

### Core (`~/.jarvis/`, provider- & OS-neutral)
- `tts_daemon.py` — becomes stateless: `/speak` accepts `{text, voice, speed}`;
  play via `sounddevice` instead of temp-WAV + `afplay`; keep single-worker FIFO
  queue, idle-exit; age-based session-file sweep on tick.
  - **Streaming worker (decision 14):** synthesize and play in a producer/
    consumer pipeline instead of render-all-then-play — chunk N plays while
    chunk N+1 is synthesized; feed numpy chunks to a `sounddevice` output stream.
  - **`chunk_text` small first chunk (decision 15):** first chunk = one sentence,
    later chunks large.
  - **Background warmup (decision 16):** kick model load on a startup thread (not
    lazily under the lock on first `/speak`). Keep `/warmup` for the arm-time ping.
  - **Thread tuning (decision 18):** set onnxruntime intra-op threads
    (≈ core count) at model load rather than the library default of 1.
  - **`/stop` endpoint (decision 17):** drain `_jobs`, terminate the tracked
    player `Popen` (or `sounddevice` stop once in-process), and set an interrupt
    flag the worker checks between chunks.
  - **Device-rate resampling (decision 19):** before playback, resample the
    numpy waveform from the model rate to the output device's native rate
    (`scipy.signal.resample_poly`), ported from jarvis-v3 `speaker.py::render`.
- `tts_client.py` — pass voice/speed through to `/speak`; cross-platform daemon
  spawn + health poll (already stdlib/urllib — drop any macOS assumptions).
- `speak.py` — read `session_id` from payload; skip unless
  `~/.jarvis/armed/<session_id>` exists; merge layered config; send effective
  voice/speed. **Provider payload shim** for locating the assistant text /
  transcript (Claude `transcript_path` known; Codex `Stop` payload TBD — verify).
- `remind.py` — read `session_id`; inject the 🔊 instruction only if that session
  is armed.
- `config.py` — implement the layered merge (defaults ⊕ global ⊕ session, env last).
- New `audio.py` — thin `sounddevice` playback wrapper.
- Replace macOS-only `say` fallback with a per-OS fallback (macOS `say`, Windows
  PowerShell `System.Speech`, Linux `espeak`/`spd-say`) selected at runtime.

### Adapters (`adapters/claude/`, `adapters/codex/`)
- **Registration:** Claude → merge hooks into `~/.claude/settings.json` (JSON);
  Codex → merge into `~/.codex/config.toml` or `~/.codex/hooks.json` (TOML/JSON).
  Register `UserPromptSubmit` + `Stop` on both; `SessionEnd` on Claude only.
- **Hook command form:** invoke a single entry script with a bare
  `python`/`python3` call and **no shell logic** (portability across shells /
  Windows).
- **Skills:** same `SKILL.md` bodies, but the embedded shell (`touch`/`rm`/`lsof`/
  `open -t`/`pkill afplay`) is replaced by calls to a small `jarvis` CLI
  (`jarvis arm-once`, `jarvis arm`, `jarvis disarm`, `jarvis stop`,
  `jarvis config ...`) so commands are OS-neutral. Codex's optional `openai.yaml`
  sidecar handled too.
- **New `/jarvis-stop` skill (decision 17):** calls `jarvis stop` to cut off
  current playback without disarming. `jarvis stop` and the old `/jarvis-off`
  both POST `/stop` to the daemon (no more `pkill afplay`).

### Installer
- Replace bash `install.sh` with a **cross-platform `install.py`**
  (`--provider claude|codex|all`, auto-detect installed providers by default).
- Steps: create `~/.jarvis/{bin,models,sessions,armed}`; build Python env with
  stdlib `venv`+`pip` (use `uv` if present); download the model from GitHub
  releases into `~/.jarvis/models/`; register hooks per provider; place skills per
  provider. Install path: `git clone` then `python install.py`.
- Cross-platform `uninstall.py` mirrors it (unregister hooks, remove `~/.jarvis/`,
  remove skill dirs).

---

## To verify during implementation (not blocking design)

- **Codex `Stop` payload:** does it include a transcript path / assistant text
  the way Claude's does? Drives the `speak.py` payload shim. If not, derive the
  spoken text another way for Codex (e.g. `PostToolUse`/`Stop` fields or a
  session-local last-message cache).
- **Windows hook execution:** confirm how Claude Code / Codex run hook `command`
  strings on Windows (bash via git-bash vs cmd/powershell). This is why the hook
  command must be a bare `python`/`python3 <entry>` call with **no shell logic** —
  verify that form works on Windows for both providers.
- **`sounddevice` on Linux:** may need `libportaudio2` present; installer should
  detect and warn with the install hint if missing.

---

## Still to plan (not yet decided)

- Exact `jarvis` CLI surface (subcommands, args, how skills invoke it).
- Codex skill invocation specifics + whether `openai.yaml` is needed.
- Migration path for existing installs under `~/.claude/jarvis/` → `~/.jarvis/`.
- Auto-barge-in policy: a manual `/stop` is decided (decision 17), but whether a
  *new* `/speak` arriving mid-playback should auto-interrupt the current one or
  queue behind it is still open — default stays FIFO for now.

---

## Verification (once built)

- Unit: config layering precedence; text-cleaning unchanged; payload shim parses
  both Claude and Codex `Stop`/`UserPromptSubmit` samples.
- Per-OS smoke: `sounddevice` plays Kokoro output on macOS/Windows/Linux.
- Resampling (decision 19): playback on a 48 kHz output device (e.g. AirPods) is
  smooth, not choppy/garbled; a same-rate device path is a no-op passthrough.
- Streaming latency: on a long (~1200-char) reply, confirm first audio starts
  after roughly one sentence of synthesis, not after the whole reply renders,
  with no audible stall between chunks (decisions 14–15).
- Warmup: first spoken reply after daemon start incurs no model-load delay
  (decision 16).
- Stop: mid-playback `/jarvis-stop` (and `jarvis stop`) cuts audio immediately
  and clears the queue; voice mode stays armed; `/jarvis-off` also stops
  playback (decision 17).
- End-to-end per provider: install with `--provider`, open a session, `/jarvis-on`,
  ask a question, confirm the 🔊 line is spoken; open a second session and confirm
  independent arming; run both providers and confirm shared-daemon FIFO.
- Cleanup: exit a Claude session → its `armed/`+`sessions/` files gone; leave a
  Codex session 6h (or force sweep) → files gone; confirm provider transcripts
  untouched.
