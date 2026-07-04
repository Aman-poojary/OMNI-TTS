# Task 02 — Per-session arming

> Part of the JARVIS cross-platform redesign. See [plan.md](../plan.md)
> (decision 4) and [CONTEXT.md](../CONTEXT.md).
> **Dependencies:** Task 01 (`~/.jarvis/` layout, `session_id` handling).

## Goal

Replace global arming with per-session flag files so one session can be armed
without affecting any other session.

## Context

Today arming is **global** via `speak_on` (persistent) and `speak_once`
(one-shot) files in `~/.claude/jarvis/`. `remind.py` (the `UserPromptSubmit`
hook) and `speak.py` (the `Stop` hook) both check these flags, so two concurrent
sessions share one on/off state. Both Claude and Codex supply `session_id` in the
hook payload.

## Expectations

- Persistent arming writes `~/.jarvis/armed/<session_id>`; `/jarvis-on` creates
  it, `/jarvis-off` removes it.
- A one-shot variant (`/jarvis`) speaks the next reply for that session, then is
  consumed after speaking.
- `speak.py` speaks only when its payload's `session_id` is armed, and consumes
  the one-shot flag after speaking.
- `remind.py` injects the 🔊 instruction only when that session is armed.
- Disarming removes only that session's flag(s) — never another session's.

## Out of scope

- Warming the daemon at arm time (Task 04).
- Session-file cleanup on exit (Task 10).
