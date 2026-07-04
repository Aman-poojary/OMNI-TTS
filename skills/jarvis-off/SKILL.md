---
name: jarvis-off
description: Turn JARVIS voice replies OFF — disarm the TTS Stop hook so replies are no longer spoken aloud. Use when the user invokes /jarvis-off or asks to disable/turn off/stop voice replies.
---

# Turn JARVIS voice OFF

Disarms the TTS Stop hook for THIS session and stops any audio still playing.

## Steps

1. Run: `python3 ~/.jarvis/bin/cli.py disarm`
   (This removes this session's arming flags and tells the daemon to stop any
   in-progress playback — no more `pkill`.)
2. Confirm briefly in text that voice replies are off. Do NOT add a 🔊 line —
   the hook is disarmed and nothing will be spoken.

To cut off a long reply WITHOUT turning voice off, use `/jarvis-stop` instead.

Related: `/jarvis` (one-shot), `/jarvis-on`, `/jarvis-config`, `/jarvis-stop`.
