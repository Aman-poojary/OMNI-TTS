---
name: jarvis-off
description: Turn JARVIS voice replies OFF — disarm the TTS Stop hook so replies are no longer spoken aloud. Use when the user invokes /jarvis-off or asks to disable/turn off/stop voice replies.
---

# Turn JARVIS voice OFF

Disarms the TTS Stop hook: removes both flag files so nothing is spoken.

## Steps

1. Run: `rm -f ~/.claude/jarvis/speak_on ~/.claude/jarvis/speak_once`
2. Optionally silence any audio that is still playing:
   `pkill -f afplay 2>/dev/null; pkill -x say 2>/dev/null` — only do this if
   the user asked to stop mid-speech (e.g. "shut up", "stop talking").
3. Confirm briefly in text that voice replies are off. Do NOT add a 🔊 line —
   the hook is disarmed and nothing will be spoken.

Related: `/jarvis` (one-shot question), `/jarvis-on`, `/jarvis-config`.
