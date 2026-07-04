# Task 03 — Stateless daemon: per-request voice/speed + in-process playback + resampling

> Part of the JARVIS cross-platform redesign. See [plan.md](../plan.md)
> (decisions 6, 8, 19) and [CONTEXT.md](../CONTEXT.md).
> **Dependencies:** Task 01 (layered config), Task 02 (per-session arming).

## Goal

Make the daemon a stateless renderer so different sessions can use different
voices, and remove the temp-WAV + `afplay` playback path in favor of in-process
`sounddevice` playback with device-rate resampling.

## Context

Today `bin/tts-daemon.py` bakes voice/speed in at daemon start from config/env.
Its `speak()` renders all chunks, concatenates them, writes ONE temp WAV, plays
it with `afplay`, then deletes it. It keeps a single FIFO worker thread and
idle-exits after `JARVIS_TTS_IDLE_EXIT` (default 1800s). One loaded Kokoro model
serves all voices (voices are embeddings in `voices-v1.0.bin`).

A working in-process + resampling reference exists in
`jarvis-v3/jarvis/speaker.py::render`: it renders to a numpy float32 array,
resamples 24 kHz → device rate via `scipy.signal.resample_poly`, then plays with
`sd.play(...)` + `sd.wait()`.

## Expectations

- `/speak` request body carries `{text, voice, speed}`. The daemon no longer
  holds voice/speed globally; `speak.py` / `tts-client.py` compute the effective
  config (Task 01) and send it per request.
- Playback is in-process via `sounddevice` on the numpy waveform — **no temp
  WAV, no `afplay`**.
- **Device-rate resampling** before playback: query the output device's
  `default_samplerate`; if it differs from the model rate (24 kHz), resample with
  `scipy.signal.resample_poly` (ratio reduced by gcd). Same-rate path is a no-op
  passthrough. This fixes choppy/garbled Bluetooth/AirPods audio.
- Single-worker FIFO ordering and idle self-exit are preserved.
- Keep the `afplay` route available as a fallback where `sounddevice`/PortAudio
  is unavailable (coordinates with Task 06).

## Out of scope

- Streaming synthesis and warmup (Task 04).
- The `/stop` endpoint (Task 05).
- Swapping the model backend to MLX (explicitly out of scope in plan.md).
