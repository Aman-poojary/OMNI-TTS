# Task 10 — Session cleanup (SessionEnd hook + age sweep)

> Part of the JARVIS cross-platform redesign. See [plan.md](../plan.md)
> (decision 7) and [CONTEXT.md](../CONTEXT.md).
> **Dependencies:** Task 01 (session files), Task 08 (Claude `SessionEnd` hook
> registration).

## Goal

Remove stale per-session files reliably, across both providers and crashed
sessions, without ever touching provider history.

## Context

Per-session files live in `~/.jarvis/armed/` and `~/.jarvis/sessions/`. Codex has
no session-end event, and any session can crash — so a hook alone is not enough.
Provider transcripts (`~/.claude/projects/**.jsonl`, `~/.codex/**`) must stay
read-only so resuming old sessions is safe.

## Expectations

- Claude `SessionEnd` hook deletes that session's `armed/` + `sessions/` files on
  exit.
- A **6-hour age-based sweep** (daemon tick / next `SessionStart`) as the
  universal backstop, covering Codex and crashed sessions.
- Cleanup touches **only `~/.jarvis/` files**. Provider transcripts/history are
  never deleted.

## Out of scope

- Any change to how transcripts are read for speech (that lives in the `speak.py`
  payload shim, Task 08).
