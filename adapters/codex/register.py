#!/usr/bin/env python3
"""Codex adapter: register hooks and place skills. Stdlib-only.

Codex's hook payload/registration is a plan open item (see plan.md "To verify").
This adapter uses ~/.codex/hooks.json with the same event names Codex converged
on (UserPromptSubmit, Stop) and bare ``<python> <entry>`` commands. Codex has NO
session-end event, so cleanup relies on the daemon's age sweep (Task 10). Skills
are copied to ~/.codex/skills/. Adjust here once the schema is confirmed.
"""

import json
import os
import shutil
import sys

HOME = os.path.expanduser("~")
CODEX_DIR = os.path.join(HOME, ".codex")
HOOKS_JSON = os.path.join(CODEX_DIR, "hooks.json")
SKILLS_DIR = os.path.join(CODEX_DIR, "skills")
BIN = os.path.join(HOME, ".jarvis", "bin")
PY = "python" if os.name == "nt" else "python3"

SKILLS = ["jarvis", "jarvis-on", "jarvis-off", "jarvis-config", "jarvis-stop"]

# No SessionEnd on Codex — see Task 10 age sweep.
HOOKS = {
    "UserPromptSubmit": ("remind.py", 10),
    "Stop": ("speak.py", 15),
}


def _command(entry):
    return f'{PY} "{os.path.join(BIN, entry)}"'


def _load():
    if os.path.exists(HOOKS_JSON):
        with open(HOOKS_JSON, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(data):
    os.makedirs(CODEX_DIR, exist_ok=True)
    with open(HOOKS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def register(repo_dir):
    data = _load()
    hooks = data.setdefault("hooks", {})
    for event, (entry, _timeout) in HOOKS.items():
        cmds = hooks.setdefault(event, [])
        if any("jarvis" in c.get("command", "") for c in cmds):
            print(f"    {event}: already registered")
            continue
        cmds.append({"command": _command(entry)})
        print(f"    {event}: registered")
    _save(data)

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
    if os.path.exists(HOOKS_JSON):
        data = _load()
        hooks = data.get("hooks", {})
        for event in HOOKS:
            cmds = hooks.get(event)
            if not cmds:
                continue
            kept = [c for c in cmds if "jarvis" not in c.get("command", "")]
            if kept:
                hooks[event] = kept
            else:
                hooks.pop(event, None)
        _save(data)
    for name in SKILLS:
        shutil.rmtree(os.path.join(SKILLS_DIR, name), ignore_errors=True)
    print("    codex: hooks + skills removed")


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    (unregister if "--remove" in sys.argv else lambda: register(repo))()
