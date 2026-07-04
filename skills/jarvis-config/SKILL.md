---
name: jarvis-config
description: Show or change JARVIS voice settings (engine, voice, speed, fallback voice, max spoken length) for this session, stored under ~/.jarvis/. Use when the user invokes /jarvis-config or asks to change the JARVIS/TTS voice, speed, engine, or voice settings, or to check voice status.
---

# JARVIS voice configuration (per session)

Settings are layered: built-in defaults < `~/.jarvis/config.json` (global) <
this session's override < environment. Changes apply to the next reply — no
restart needed. `/jarvis-config` edits THIS session's override.

Keys:
- `engine`: `"kokoro"` (local Kokoro-82M daemon, default) or `"say"` (system TTS)
- `voice`: Kokoro voice. Good options: `bm_george` (default, British male),
  `bm_lewis`, `am_michael`, `am_adam` (American male), `af_heart`, `af_bella`
- `speed`: Kokoro speed multiplier (e.g. `0.9` slower, `1.2` faster)
- `say_voice`: system-TTS fallback voice (default `Daniel`)
- `max_chars`: truncate spoken text beyond this many characters (default 1200)

## No arguments → show status, then ask what to change

Run and present the output conversationally:

```bash
python3 ~/.jarvis/bin/cli.py status
```

This prints the session id, armed state, daemon state, and the effective config.
Then ask whether they want to change a setting.

## Changing a setting

Set one key for this session (validated and cast automatically):

```bash
python3 ~/.jarvis/bin/cli.py config voice am_michael
python3 ~/.jarvis/bin/cli.py config speed 1.2
```

Same for `engine`, `say_voice`, `max_chars`. Confirm the new value to the user.

## Testing a new voice

Speak a test line through the real pipeline (uses this session's config):

```bash
python3 ~/.jarvis/bin/cli.py say "Voice check complete, sir."
```

Related: `/jarvis` (one-shot), `/jarvis-on`, `/jarvis-off`, `/jarvis-stop`.
