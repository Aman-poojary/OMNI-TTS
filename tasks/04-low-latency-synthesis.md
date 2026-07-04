# Task 04 — Low-latency synthesis: streaming, small first chunk, warmup, thread tuning

> Part of the JARVIS cross-platform redesign. See [plan.md](../plan.md)
> (decisions 14, 15, 16, 18) and [CONTEXT.md](../CONTEXT.md).
> **Dependencies:** Task 03 (in-process `sounddevice` playback).

## Goal

Cut time-to-first-audio and overall synthesis latency so replies start speaking
quickly and long replies don't sit in silence.

## Context

Today the daemon renders the *whole* reply before any audio plays (multi-second
silence on long replies), loads the model **lazily under a lock on the first
`/speak`**, and runs onnxruntime at the library default of 1 intra-op thread.
`chunk_text` splits text into ~280-char sentence groups (`MAX_CHUNK_CHARS=280`).

## Expectations

- **Streaming pipeline** (producer/consumer): synthesize chunk N, hand it to a
  playback consumer, synthesize chunk N+1 while N plays — feed numpy chunks to a
  `sounddevice` output stream. Never stall mid-reply; if the producer falls
  behind, resume on natural sentence boundaries.
- **Small first chunk:** `chunk_text` emits the first chunk as a single sentence;
  later chunks stay large. First audio then lands after one sentence of synthesis.
- **Background warmup:** load the model on a startup thread when the daemon boots
  (not lazily under the lock on first `/speak`). Keep a `/warmup` endpoint for an
  arm-time ping — `/jarvis-on` and `/jarvis` ping it (coordinates with Task 02).
  Optionally synthesize a throwaway one-word utterance to warm the ONNX graph.
- **Thread tuning:** set onnxruntime intra-op threads (≈ physical core count) at
  model load via session options or `OMP_NUM_THREADS`, instead of the default 1.
  Benchmark to pick the default.

## Out of scope

- The `/stop` endpoint / barge-in (Task 05).
