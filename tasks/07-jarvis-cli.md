# Task 07 — `jarvis` CLI

> Part of the JARVIS cross-platform redesign. See [plan.md](../plan.md)
> ("Adapters" + "Still to plan") and [CONTEXT.md](../CONTEXT.md).
> **Dependencies:** Task 01 (`~/.jarvis/` + config), Task 02 (arming files),
> Task 04 (`/warmup`), Task 05 (`/stop`).

## Goal

Provide an OS-neutral command surface so skills contain no embedded shell logic —
this is the portability seam between skills and the core.

## Context

Today skills embed shell (`touch` / `rm` / `lsof` / `open -t` / `pkill afplay`),
which is macOS-specific and not portable to Windows. The exact CLI surface is
still open in plan.md — propose and lock it here.

## Expectations

- A `jarvis` CLI exposing at least: `arm-once`, `arm`, `disarm`, `stop`,
  `config ...`. (`status` and `say` for testing are welcome.)
- Behavior per subcommand:
  - `arm` / `arm-once` — write the session flag (Task 02) and ping `/warmup`.
  - `disarm` — remove the session flag(s) and call stop.
  - `stop` — POST `/stop` to the daemon.
  - `config` — read/write the per-session override JSON (Task 01).
- No OS-specific shell assumptions inside the CLI.
- Reachable by both providers' skills via a bare `python`/`python3` invocation.

## Out of scope

- Registering hooks or placing skills per provider (Task 08).
