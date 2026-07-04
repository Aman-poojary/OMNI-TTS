#!/usr/bin/env python3
"""Claude Code adapter: register hooks and place skills. Stdlib-only.

Hooks are merged into ~/.claude/settings.json as bare ``<python> <entry>`` calls
with no shell logic (Windows/shell portability). Claude supports SessionEnd, so
cleanup is wired here too. Skills are copied into ~/.claude/skills/.
"""

import json
import os
import shutil
import sys

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
SKILLS_DIR = os.path.join(CLAUDE_DIR, "skills")
BIN = os.path.join(HOME, ".jarvis", "bin")
PY = "python" if os.name == "nt" else "python3"

SKILLS = ["jarvis", "jarvis-on", "jarvis-off", "jarvis-config", "jarvis-stop"]

# event -> (entry script, timeout seconds)
HOOKS = {
    "UserPromptSubmit": ("remind.py", 10),
    "Stop": ("speak.py", 15),
    "SessionEnd": ("session_end.py", 10),
}


def _command(entry):
    return f'{PY} "{os.path.join(BIN, entry)}"'


def _entry_has_jarvis(entry):
    return any("jarvis" in h.get("command", "") for h in entry.get("hooks", []))


def _register_statusline(settings):
    """Point statusLine at the JARVIS segment when none is configured. An
    existing non-jarvis statusLine is left alone — append the segment there
    instead (see README)."""
    cmd = _command("statusline.py")
    existing = settings.get("statusLine") or {}
    if not existing.get("command"):
        settings["statusLine"] = {"type": "command", "command": cmd}
        print("    statusLine: registered")
    elif "jarvis" in existing["command"]:
        print("    statusLine: already registered")
    else:
        print("    statusLine: existing non-jarvis command kept; append")
        print(f'      the segment yourself: echo "$input" | {cmd}')


def _load_settings():
    if os.path.exists(SETTINGS):
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_settings(settings):
    os.makedirs(CLAUDE_DIR, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def register(repo_dir):
    settings = _load_settings()
    hooks = settings.setdefault("hooks", {})
    for event, (entry, timeout) in HOOKS.items():
        entries = hooks.setdefault(event, [])
        new = {"hooks": [{"type": "command", "command": _command(entry), "timeout": timeout}]}
        stale = [e for e in entries if _entry_has_jarvis(e) and e != new]
        if stale:
            # replace outdated jarvis registrations (e.g. old install paths)
            hooks[event] = entries = [e for e in entries if not _entry_has_jarvis(e)]
            entries.append(new)
            print(f"    {event}: replaced stale registration")
        elif any(_entry_has_jarvis(e) for e in entries):
            print(f"    {event}: already registered")
        else:
            entries.append(new)
            print(f"    {event}: registered")
    _register_statusline(settings)
    _save_settings(settings)

    os.makedirs(SKILLS_DIR, exist_ok=True)
    for name in SKILLS:
        src = os.path.join(repo_dir, "skills", name, "SKILL.md")
        if not os.path.exists(src):
            continue
        dst = os.path.join(SKILLS_DIR, name)
        os.makedirs(dst, exist_ok=True)
        shutil.copy(src, os.path.join(dst, "SKILL.md"))
    print(f"    skills: placed in {SKILLS_DIR}")


def unregister():
    if os.path.exists(SETTINGS):
        settings = _load_settings()
        hooks = settings.get("hooks", {})
        for event in HOOKS:
            entries = hooks.get(event)
            if not entries:
                continue
            kept = [e for e in entries if not _entry_has_jarvis(e)]
            if kept:
                hooks[event] = kept
            else:
                hooks.pop(event, None)
        if "jarvis" in (settings.get("statusLine") or {}).get("command", ""):
            settings.pop("statusLine", None)
        _save_settings(settings)
    for name in SKILLS:
        shutil.rmtree(os.path.join(SKILLS_DIR, name), ignore_errors=True)
    print("    claude: hooks + skills removed")


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    (unregister if "--remove" in sys.argv else lambda: register(repo))()
