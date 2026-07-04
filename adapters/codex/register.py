#!/usr/bin/env python3
"""Codex adapter: register hooks and place skills. Stdlib-only.

This adapter uses ~/.codex/hooks.json with Codex hook event names
(SessionStart, UserPromptSubmit, Stop) and bare ``<python> <entry>`` commands.
Codex has NO session-end event, so cleanup relies on the daemon's age sweep and
the SessionStart sweep backstop (Task 10).

Codex user skills are copied to ~/.agents/skills/. Small custom prompt shims are
also written to ~/.codex/prompts/ so slash-command users can discover them as
/prompts:jarvis* in the CLI. Codex does not expose skills as plain /jarvis
commands; skills are invoked with $jarvis, via /skills, or implicitly.
"""

import json
import os
import shutil
import sys

HOME = os.path.expanduser("~")
CODEX_DIR = os.path.join(HOME, ".codex")
HOOKS_JSON = os.path.join(CODEX_DIR, "hooks.json")
PROMPTS_DIR = os.path.join(CODEX_DIR, "prompts")
SKILLS_DIR = os.path.join(HOME, ".agents", "skills")
LEGACY_SKILLS_DIR = os.path.join(CODEX_DIR, "skills")
BIN = os.path.join(HOME, ".jarvis", "bin")
PY = "python" if os.name == "nt" else "python3"

SKILLS = ["jarvis", "jarvis-on", "jarvis-off", "jarvis-config", "jarvis-stop"]

# No SessionEnd on Codex — see Task 10 age sweep / SessionStart backstop.
HOOKS = {
    "SessionStart": ("session_sweep.py", 10),
    "UserPromptSubmit": ("remind.py", 10),
    "Stop": ("speak.py", 15),
}

PROMPTS = {
    "jarvis": (
        "Answer one question aloud, JARVIS-style.",
        "$jarvis $ARGUMENTS\n",
    ),
    "jarvis-on": (
        "Speak every reply in this Codex session until turned off.",
        "$jarvis-on $ARGUMENTS\n",
    ),
    "jarvis-off": (
        "Silence this Codex session and stop any audio playing.",
        "$jarvis-off $ARGUMENTS\n",
    ),
    "jarvis-config": (
        "Show or change this Codex session's Jarvis voice settings.",
        "$jarvis-config $ARGUMENTS\n",
    ),
    "jarvis-stop": (
        "Stop current Jarvis playback without disarming the session.",
        "$jarvis-stop $ARGUMENTS\n",
    ),
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


def _write_prompt(name, description, body):
    path = os.path.join(PROMPTS_DIR, f"{name}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write(f"description: {description}\n")
        f.write("argument-hint: [prompt]\n")
        f.write("---\n\n")
        f.write(body)


def _entry_has_jarvis(entry):
    if "jarvis" in entry.get("command", ""):
        return True
    return any("jarvis" in h.get("command", "") for h in entry.get("hooks", []))


def register(repo_dir):
    data = _load()
    hooks = data.setdefault("hooks", {})
    for event, (entry, timeout) in HOOKS.items():
        entries = hooks.setdefault(event, [])
        kept = [e for e in entries if not _entry_has_jarvis(e)]
        if len(kept) != len(entries):
            hooks[event] = kept
            entries = kept
            print(f"    {event}: updated existing registration")
        elif any(_entry_has_jarvis(e) for e in entries):
            print(f"    {event}: already registered")
            continue
        entries.append({"hooks": [{"type": "command", "command": _command(entry), "timeout": timeout}]})
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

    os.makedirs(PROMPTS_DIR, exist_ok=True)
    for name, (description, body) in PROMPTS.items():
        _write_prompt(name, description, body)
    print(f"    prompt shims: placed in {PROMPTS_DIR}")


def unregister():
    if os.path.exists(HOOKS_JSON):
        data = _load()
        hooks = data.get("hooks", {})
        for event in HOOKS:
            cmds = hooks.get(event)
            if not cmds:
                continue
            kept = [e for e in cmds if not _entry_has_jarvis(e)]
            if kept:
                hooks[event] = kept
            else:
                hooks.pop(event, None)
        _save(data)
    for name in SKILLS:
        shutil.rmtree(os.path.join(SKILLS_DIR, name), ignore_errors=True)
        shutil.rmtree(os.path.join(LEGACY_SKILLS_DIR, name), ignore_errors=True)
        try:
            os.remove(os.path.join(PROMPTS_DIR, f"{name}.md"))
        except FileNotFoundError:
            pass
    print("    codex: hooks + skills removed")


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    (unregister if "--remove" in sys.argv else lambda: register(repo))()
