# Task 01 — Relocate core to `~/.jarvis/` + layered config

> Part of the JARVIS cross-platform redesign. See [plan.md](../plan.md)
> (decisions 2, 5) and [CONTEXT.md](../CONTEXT.md) (current implementation).
> **Dependencies:** none — this is the foundation every later task builds on.

## Goal

Establish the provider-neutral install root `~/.jarvis/` and a per-session,
layered configuration system that everything else depends on.

## Context

Today the core scripts live in `~/.claude/jarvis/bin/` and config is a single
**global** `~/.claude/jarvis/config.json`, read by `bin/jarvis_config.py` over
built-in `DEFAULTS` (`engine`, `voice`, `speed`, `say_voice`, `max_chars`). Env
vars override per run. This couples the tool to Claude and to one global voice.

The new root is `~/.jarvis/` with subdirs `bin/ models/ sessions/ armed/`.
Providers will get only *pointers* into this root (later tasks). Config becomes
layered and per-session. One loaded model still serves all voices.

## Expectations

- Use the new layout: `~/.jarvis/{bin,models,sessions,armed}`.
- A `config.py` module implementing a layered merge with precedence
  **env > session override > global default > built-in defaults**:
  - `~/.jarvis/config.json` — global defaults.
  - `~/.jarvis/sessions/<session_id>.json` — per-session overrides.
- `load_config(session_id)` returns the effective config for a session and is
  **re-read on every reply** (edits apply without restarting the daemon).
- Built-in defaults preserve current behavior: `voice=bm_george`, `speed=1.0`,
  `say_voice=Daniel`, `max_chars=1200`, and the existing `engine` default.
- Config code is stdlib-only (runs under any `python3`), like today's scripts.

## Out of scope

- Provider registration, arming, and daemon changes — later tasks.
- Migrating an existing `~/.claude/jarvis/` install (tracked as an open item).
