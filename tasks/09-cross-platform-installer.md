# Task 09 — Cross-platform installer + uninstaller + model download

> Part of the JARVIS cross-platform redesign. See [plan.md](../plan.md)
> (decisions 10, 11, 12) and [CONTEXT.md](../CONTEXT.md).
> **Dependencies:** Tasks 01–08 (the installer wires up everything they define).

## Goal

Deliver one clone-and-run install story that is identical on macOS, Windows, and
Linux.

## Context

Today `install.sh` is bash and hard-exits on non-Darwin. It uses `uv` to build a
py3.11 venv and `curl`s the ~340 MB model into `~/.claude/jarvis/models/`. The
daemon runs under the venv; the hook/client scripts are stdlib-only and run under
any `python3`.

## Expectations

- `install.py` with `--provider claude|codex|all` (auto-detect installed
  providers by default). Steps:
  - create `~/.jarvis/{bin,models,sessions,armed}`;
  - build a Python env with stdlib `venv` + `pip`, using `uv` opportunistically
    if present (no hard `uv` dependency);
  - download the model from GitHub releases into `~/.jarvis/models/`;
  - register hooks per provider (Task 08);
  - place skills per provider (Task 08).
- `uninstall.py` mirrors it: unregister hooks, remove `~/.jarvis/`, remove skill
  dirs.
- Both are idempotent (skip work already done).
- On Linux, detect missing `libportaudio2` and warn with the install hint.
- Install path is `git clone` then `python install.py` — no publish pipeline.

## Out of scope

- Migrating an existing `~/.claude/jarvis/` install (open item in plan.md).
- Publishing to a package registry.
