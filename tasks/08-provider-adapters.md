# Task 08 — Provider adapters (Claude Code + Codex)

> Part of the JARVIS cross-platform redesign. See [plan.md](../plan.md)
> (decisions 1, 3; "Adapters" section) and [CONTEXT.md](../CONTEXT.md).
> **Dependencies:** Task 07 (`jarvis` CLI the skills call), and the core tasks
> (01–06) whose behavior the hooks drive.

## Goal

Register hooks and place skills per provider, pointing at the shared core, so one
core serves both Claude Code and Codex with only thin per-provider glue.

## Context

Both providers expose `UserPromptSubmit` (with `additionalContext` injection) and
`Stop` hooks fed JSON on stdin, and both read `SKILL.md` files (YAML frontmatter
`name`/`description`). Only the *registration location*, *hook payload schema*,
and *session-end availability* differ:
- Claude → `~/.claude/settings.json` (JSON); has a `SessionEnd` hook.
- Codex → `~/.codex/config.toml` or `~/.codex/hooks.json` (TOML/JSON); no
  session-end event.

## Expectations

- `adapters/claude/` merges hooks into `~/.claude/settings.json`;
  `adapters/codex/` merges into the Codex config. Register `UserPromptSubmit` +
  `Stop` on both; `SessionEnd` on Claude only.
- Hook command form is a bare `python`/`python3 <entry>` call with **no shell
  logic** (Windows/shell portability).
- Skills (`jarvis`, `jarvis-on`, `jarvis-off`, `jarvis-config`, `jarvis-stop`)
  reuse the same `SKILL.md` bodies but call the `jarvis` CLI (Task 07) instead of
  embedded shell. Handle Codex's optional `openai.yaml` sidecar if needed.
- **`speak.py` payload shim:** locate the assistant text / transcript per
  provider. Claude's `transcript_path` is known; verify Codex's `Stop` payload
  and derive the spoken text accordingly (see Open Items in plan.md — if Codex
  lacks a transcript path, use its `Stop` fields or a session-local last-message
  cache).

## Out of scope

- The installer that invokes these adapters (Task 09).
- Session-file cleanup wiring (Task 10) — this task only registers the hooks.
