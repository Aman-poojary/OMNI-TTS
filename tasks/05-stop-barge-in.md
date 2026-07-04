# Task 05 — Stop / barge-in

> Part of the JARVIS cross-platform redesign. See [plan.md](../plan.md)
> (decision 17) and [CONTEXT.md](../CONTEXT.md).
> **Dependencies:** Task 03 (in-process playback), Task 07 (`jarvis` CLI) for the
> command surface; the daemon endpoint can land first.

## Goal

Let the user cut off the current spoken reply instantly, without disarming voice
mode.

## Context

Today `/jarvis-off` relied on a blanket `pkill afplay`. Once playback is
in-process via `sounddevice` (Task 03) there is no `afplay` process to kill, so a
proper stop mechanism is needed.

## Expectations

- Daemon `/stop` (POST) endpoint that:
  - drains the pending `_jobs` queue, and
  - aborts the currently playing utterance,
  - plus an interrupt flag the worker checks between chunks.
- Exposed as a `jarvis stop` CLI command (Task 07) and a `/jarvis-stop` skill.
- `/jarvis-off` also calls stop (replaces the old `pkill afplay`).
- A *new* request arriving mid-playback stays **FIFO** by default (it queues; it
  does not auto-interrupt current playback).

## Out of scope

- Auto-barge-in (new request auto-interrupting playback) — explicitly deferred in
  plan.md; manual stop only.
