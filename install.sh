#!/usr/bin/env bash
# Install the JARVIS voice system for Claude Code.
#
# What it does:
#   1. Copies the hook/daemon scripts to ~/.claude/jarvis/bin/
#   2. Copies the /jarvis* skills to ~/.claude/skills/
#   3. Creates a Python 3.11 venv (via uv) with kokoro-onnx + soundfile
#   4. Downloads the Kokoro-82M model files (~340 MB, one-time)
#   5. Registers the Stop + UserPromptSubmit hooks in ~/.claude/settings.json
#
# Safe to re-run: it updates scripts/skills in place, skips the venv and
# model downloads if already present, and never duplicates hook entries.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
JARVIS_DIR="$HOME/.claude/jarvis"
SKILLS_DIR="$HOME/.claude/skills"
SETTINGS="$HOME/.claude/settings.json"
MODEL_BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

if [ "$(uname)" != "Darwin" ]; then
  echo "error: JARVIS uses macOS audio (afplay/say); this installer supports macOS only." >&2
  exit 1
fi

echo "==> Installing scripts to $JARVIS_DIR/bin"
mkdir -p "$JARVIS_DIR/bin" "$JARVIS_DIR/models" "$SKILLS_DIR"
cp "$REPO_DIR"/bin/*.py "$JARVIS_DIR/bin/"

if [ ! -f "$JARVIS_DIR/config.json" ]; then
  cp "$REPO_DIR/config.default.json" "$JARVIS_DIR/config.json"
  echo "==> Wrote default config to $JARVIS_DIR/config.json"
else
  echo "==> Keeping existing $JARVIS_DIR/config.json"
fi

echo "==> Installing skills (/jarvis, /jarvis-on, /jarvis-off, /jarvis-config)"
for s in jarvis jarvis-on jarvis-off jarvis-config; do
  mkdir -p "$SKILLS_DIR/$s"
  cp "$REPO_DIR/skills/$s/SKILL.md" "$SKILLS_DIR/$s/SKILL.md"
done

if [ ! -x "$JARVIS_DIR/venv/bin/python" ]; then
  echo "==> Creating Python venv (kokoro-onnx + soundfile)"
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.11 "$JARVIS_DIR/venv"
    uv pip install --python "$JARVIS_DIR/venv/bin/python" \
      kokoro-onnx soundfile "setuptools<81"
  else
    echo "error: 'uv' not found. Install it first:" >&2
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
  fi
else
  echo "==> Keeping existing venv"
fi

for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [ ! -f "$JARVIS_DIR/models/$f" ]; then
    echo "==> Downloading $f (one-time)"
    curl -L --fail --progress-bar -o "$JARVIS_DIR/models/$f" "$MODEL_BASE/$f"
  else
    echo "==> Keeping existing model file $f"
  fi
done

echo "==> Registering hooks in $SETTINGS"
python3 - "$SETTINGS" <<'PY'
import json, os, sys

path = sys.argv[1]
os.makedirs(os.path.dirname(path), exist_ok=True)
settings = {}
if os.path.exists(path):
    with open(path) as f:
        settings = json.load(f)

# The [ -f ... ] guard means a missing script can never block prompts:
# a bare `python3 missing.py` exits 2, which Claude Code treats as "block".
HOOKS = {
    "UserPromptSubmit": {
        "command": 'f="$HOME/.claude/jarvis/bin/remind.py"; [ -f "$f" ] && python3 "$f" || true',
        "timeout": 10,
    },
    "Stop": {
        "command": 'f="$HOME/.claude/jarvis/bin/speak.py"; [ -f "$f" ] && python3 "$f" || true',
        "timeout": 15,
    },
}

hooks = settings.setdefault("hooks", {})
for event, spec in HOOKS.items():
    entries = hooks.setdefault(event, [])
    already = any(
        "jarvis" in h.get("command", "")
        for e in entries
        for h in e.get("hooks", [])
    )
    if already:
        print(f"    {event}: jarvis hook already registered, skipping")
        continue
    entries.append({"hooks": [{"type": "command", **spec}]})
    print(f"    {event}: registered")

with open(path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
PY

# Reload the daemon if an old one is resident, so new code takes effect.
if lsof -ti :7739 >/dev/null 2>&1; then
  echo "==> Restarting TTS daemon"
  lsof -ti :7739 | xargs kill 2>/dev/null || true
fi

echo
echo "Done. Restart Claude Code so the /jarvis* commands appear, then try:"
echo "  /jarvis what can you do?"
echo "  /jarvis-on         # speak every reply"
echo "  /jarvis-off        # silence"
echo "  /jarvis-config     # change voice / speed / engine"
