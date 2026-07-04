#!/usr/bin/env bash
# Remove the JARVIS voice system: hooks, skills, scripts, venv, and models.
set -euo pipefail

SETTINGS="$HOME/.claude/settings.json"

echo "==> Stopping TTS daemon (if running)"
lsof -ti :7739 2>/dev/null | xargs kill 2>/dev/null || true

echo "==> Removing jarvis hooks from $SETTINGS"
if [ -f "$SETTINGS" ]; then
python3 - "$SETTINGS" <<'PY'
import json, sys

path = sys.argv[1]
with open(path) as f:
    settings = json.load(f)

hooks = settings.get("hooks", {})
for event in ("UserPromptSubmit", "Stop"):
    entries = hooks.get(event)
    if not entries:
        continue
    kept = [
        e for e in entries
        if not any("jarvis" in h.get("command", "") for h in e.get("hooks", []))
    ]
    if kept:
        hooks[event] = kept
    else:
        del hooks[event]

with open(path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
print("    hooks removed")
PY
fi

echo "==> Removing files"
rm -rf "$HOME/.claude/jarvis"
for s in jarvis jarvis-on jarvis-off jarvis-config; do
  rm -rf "$HOME/.claude/skills/$s"
done

echo "Done. Restart Claude Code to clear the /jarvis* commands from the menu."
