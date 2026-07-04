---
name: jarvis
description: Answer one question aloud, JARVIS-style, via the TTS Stop hook (one-shot). Use when the user invokes /jarvis with a question or asks Claude to speak/say an answer out loud once. For persistent voice mode use jarvis-on/jarvis-off; for voice settings use jarvis-config.
---

# JARVIS one-shot spoken answer

A Stop hook (`~/.claude/jarvis/bin/speak.py`) speaks the final reply aloud —
but only when armed via flag files in `~/.claude/jarvis/`. This skill arms it
for ONE reply. Related commands: `/jarvis-on`, `/jarvis-off`, `/jarvis-config`.

## Steps

1. Arm the one-shot flag:
   `mkdir -p ~/.claude/jarvis && touch ~/.claude/jarvis/speak_once`
2. Answer the user's question normally (the arguments are the question).
   If there is no question, just arm the flag and reply with something short
   and JARVIS-like (e.g. "At your service, sir.").
3. End the final message with the voice-summary line (see below). The hook
   speaks that line once, then disarms itself.

## Writing the voice line (REQUIRED whenever a reply will be spoken)

End the final message with one paragraph starting with 🔊:

```
🔊 <spoken-style answer>
```

Rules:
- Start the line with 🔊 (the hook keys on it); keep it as the LAST
  paragraph of the message.
- Write it as JARVIS answering Tony Stark: directly answer what the user
  asked — the actual findings, numbers, names, and conclusions — not a
  meta-description of the work done ("I fixed it" is wrong; say what the
  answer IS).
- Straight to the point, no filler. As short or as long as a complete
  answer requires.
- Plain conversational prose for the ear: no markdown, no code, no file
  paths, no symbols. Address the user as "sir" where natural.
- If the line is missing, the hook falls back to speaking the whole reply
  (truncated at max_chars) — always write the line so the user hears a
  proper spoken answer instead.

## How it speaks (for reference)

- Engine: Kokoro-82M (ONNX) served by a warm local daemon
  (`~/.claude/jarvis/bin/tts-daemon.py`, port 7739, auto-started, idles out
  after 30 min). Falls back to macOS `say` if the daemon is unavailable.
- Settings live in `~/.claude/jarvis/config.json` — change them with
  `/jarvis-config`.
- The hook never blocks: it detaches the speaker process and always exits 0.
- Arming flags before answering is correct — the hook fires at Stop, after
  the reply is complete.
