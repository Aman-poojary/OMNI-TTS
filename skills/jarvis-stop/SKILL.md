---
name: jarvis-stop
description: Cut off the JARVIS spoken reply that is currently playing, without turning voice mode off. Use when the user invokes /jarvis-stop or says "stop talking" / "shut up" / "be quiet" mid-speech but wants voice replies to stay armed.
---

# Stop the current spoken reply

Interrupts the reply the daemon is speaking right now and clears anything
queued, WITHOUT disarming voice mode — the next reply will still be spoken.

## Steps

1. Run: `python3 ~/.jarvis/bin/cli.py stop`
2. Confirm briefly in text. Do NOT add a 🔊 line for this turn — you just asked
   it to stop talking.

Use `/jarvis-off` instead if the user wants to turn voice replies off entirely.

Related: `/jarvis`, `/jarvis-on`, `/jarvis-off`, `/jarvis-config`.
