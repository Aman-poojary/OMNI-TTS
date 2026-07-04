"""Per-OS system-TTS fallback. Stdlib-only.

Used when the Kokoro daemon is unavailable, so a broken model still produces an
audible voice instead of silence:
    macOS   -> say
    Windows -> SAPI via PowerShell System.Speech
    Linux   -> spd-say / espeak
"""

import os
import shutil
import subprocess
import sys


def speak(text, say_voice=None):
    """Speak text via the platform's system TTS. Returns True if something ran."""
    if not text:
        return False
    if sys.platform == "darwin":
        return _macos(text, say_voice)
    if os.name == "nt":
        return _windows(text, say_voice)
    return _linux(text, say_voice)


def _macos(text, voice):
    if not shutil.which("say"):
        return False
    cmd = ["say"]
    if voice:
        cmd += ["-v", voice]
    cmd.append(text)
    subprocess.run(cmd)
    return True


def _windows(text, voice):
    if not shutil.which("powershell"):
        return False
    # Pass text/voice via env to avoid PowerShell quoting/injection issues.
    env = dict(os.environ, JARVIS_SAY_TEXT=text, JARVIS_SAY_VOICE=voice or "")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "if ($env:JARVIS_SAY_VOICE) { try { $s.SelectVoice($env:JARVIS_SAY_VOICE) } catch {} }; "
        "$s.Speak($env:JARVIS_SAY_TEXT)"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env)
    return True


def _linux(text, voice):
    if shutil.which("spd-say"):
        cmd = ["spd-say", "--wait"]
        if voice:
            cmd += ["-y", voice]
        cmd.append(text)
        subprocess.run(cmd)
        return True
    if shutil.which("espeak"):
        cmd = ["espeak"]
        if voice:
            cmd += ["-v", voice]
        cmd.append(text)
        subprocess.run(cmd)
        return True
    return False
