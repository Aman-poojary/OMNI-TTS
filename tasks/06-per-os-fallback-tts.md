# Task 06 — Per-OS system-TTS fallback

> Part of the JARVIS cross-platform redesign. See [plan.md](../plan.md)
> (decision 13) and [CONTEXT.md](../CONTEXT.md).
> **Dependencies:** Task 03 (playback path this falls back from).

## Goal

Guarantee an audible voice when Kokoro is unavailable, so a broken model produces
a voice instead of silence.

## Context

Today the only fallback is macOS `say`: `tts-client.py` falls back to `say` when
the daemon is unreachable. This does not work on Windows or Linux.

## Expectations

- A per-OS fallback selected at runtime:
  - macOS → `say`
  - Windows → SAPI via PowerShell `System.Speech`
  - Linux → `espeak` / `spd-say`
- Used when the model/daemon path fails.
- Respects the effective `say_voice` config where the platform supports voice
  selection.

## Out of scope

- Bundling or installing the system TTS engines — the installer (Task 09) only
  detects/warns about missing dependencies.
