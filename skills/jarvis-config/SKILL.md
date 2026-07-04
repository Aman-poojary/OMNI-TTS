---
name: jarvis-config
description: Show or change JARVIS voice settings (engine, voice, speed, fallback voice, max spoken length) stored in ~/.claude/jarvis/config.json, or open the file for manual editing. Use when the user invokes /jarvis-config or asks to change the JARVIS/TTS voice, speed, engine, or voice settings, or to check voice status.
---

# JARVIS voice configuration

Settings live in `~/.claude/jarvis/config.json` and are re-read on every
spoken reply — changes apply to the next reply, no restart needed.

Keys:
- `engine`: `"kokoro"` (local Kokoro-82M daemon, default) or `"say"` (macOS)
- `voice`: Kokoro voice. Good options: `bm_george` (default, British male),
  `bm_lewis` (British male), `am_michael`, `am_adam` (American male),
  `af_heart`, `af_bella` (American female)
- `speed`: Kokoro speed multiplier (e.g. `0.9` slower, `1.2` faster)
- `say_voice`: macOS `say` fallback voice (default `Daniel`)
- `max_chars`: truncate spoken text beyond this many characters (default 1200)

## No arguments → show status, then ask what to change

Run and present the output conversationally:

```bash
echo "config:"; cat ~/.claude/jarvis/config.json
echo "flags:"; ls ~/.claude/jarvis/ | grep -E '^speak_' || echo "voice off"
echo "daemon:"; lsof -ti :7739 >/dev/null 2>&1 && echo running || echo "not running (starts on demand)"
```

Then ask whether they want to change a setting or edit the file manually.

## Changing a setting

Update the key with a python3 one-liner (keeps valid JSON), e.g. voice:

```bash
python3 -c "
import json,os
p=os.path.expanduser('~/.claude/jarvis/config.json')
c=json.load(open(p)); c['voice']='am_michael'
json.dump(c,open(p,'w'),indent=2); print(json.dumps(c,indent=2))
"
```

Same pattern for `speed` (float), `engine`, `say_voice`, `max_chars` (int).
Validate values: engine must be `kokoro` or `say`; speed a number roughly
0.5–2.0. Confirm the new config to the user.

## Manual editing

If the user wants to edit the file themselves, open it:
`open -t ~/.claude/jarvis/config.json` (or tell them the path).

## Testing a new voice

If asked to demo, speak a test line through the real pipeline:

```bash
python3 ~/.claude/jarvis/bin/tts-client.py "Voice check complete, sir."
```

Related: `/jarvis` (one-shot question), `/jarvis-on`, `/jarvis-off`.
