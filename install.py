#!/usr/bin/env python3
"""Cross-platform installer for JARVIS. Runs on macOS, Windows, Linux.

    python install.py [--provider claude|codex|all]

Default auto-detects installed providers (~/.claude, ~/.codex). Steps:
  1. create ~/.jarvis/{bin,models,sessions,armed}
  2. copy the core scripts into ~/.jarvis/bin/
  3. write the default global config (if absent)
  4. build a Python env (stdlib venv+pip; uses uv if present)
  5. download the Kokoro model files into ~/.jarvis/models/
  6. register hooks + place skills per provider (via adapters/)

Idempotent: re-running updates scripts and skips work already done.
"""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import urllib.request

REPO = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
JARVIS = os.path.join(HOME, ".jarvis")
BIN = os.path.join(JARVIS, "bin")
MODELS = os.path.join(JARVIS, "models")
VENV = os.path.join(JARVIS, "venv")
CONFIG = os.path.join(JARVIS, "config.json")

MODEL_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
MODEL_FILES = ["kokoro-v1.0.onnx", "voices-v1.0.bin"]
PIP_PKGS = ["kokoro-onnx", "soundfile", "sounddevice", "scipy", "setuptools<81"]


def venv_python():
    if os.name == "nt":
        return os.path.join(VENV, "Scripts", "python.exe")
    return os.path.join(VENV, "bin", "python")


def make_dirs():
    for d in (BIN, MODELS, os.path.join(JARVIS, "sessions"), os.path.join(JARVIS, "armed")):
        os.makedirs(d, exist_ok=True)
    print(f"==> Layout ready at {JARVIS}")


def copy_scripts():
    for name in os.listdir(os.path.join(REPO, "bin")):
        if name.endswith(".py"):
            shutil.copy(os.path.join(REPO, "bin", name), os.path.join(BIN, name))
    print(f"==> Copied scripts to {BIN}")


def write_config():
    if os.path.exists(CONFIG):
        print(f"==> Keeping existing {CONFIG}")
        return
    src = os.path.join(REPO, "config.default.json")
    if os.path.exists(src):
        shutil.copy(src, CONFIG)
        print(f"==> Wrote default config to {CONFIG}")


def build_venv():
    if os.path.exists(venv_python()):
        print("==> Keeping existing venv")
        return
    print("==> Building Python venv")
    if shutil.which("uv"):
        subprocess.check_call(["uv", "venv", VENV])
        subprocess.check_call(["uv", "pip", "install", "--python", venv_python(), *PIP_PKGS])
    else:
        subprocess.check_call([sys.executable, "-m", "venv", VENV])
        subprocess.check_call([venv_python(), "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([venv_python(), "-m", "pip", "install", *PIP_PKGS])


def download_models():
    for fname in MODEL_FILES:
        dst = os.path.join(MODELS, fname)
        if os.path.exists(dst):
            print(f"==> Keeping model file {fname}")
            continue
        print(f"==> Downloading {fname} (one-time, ~large)")
        urllib.request.urlretrieve(f"{MODEL_BASE}/{fname}", dst)


def warn_portaudio():
    if sys.platform.startswith("linux") and not any(
        os.path.exists(os.path.join(p, "libportaudio.so.2"))
        for p in ("/usr/lib", "/usr/lib/x86_64-linux-gnu", "/usr/lib64")
    ):
        print("!!  libportaudio2 not found — sounddevice needs it. Install e.g.:")
        print("      sudo apt-get install libportaudio2   (Debian/Ubuntu)")


def _load_adapter(provider):
    path = os.path.join(REPO, "adapters", provider, "register.py")
    spec = importlib.util.spec_from_file_location(f"jarvis_adapter_{provider}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def detect_providers():
    found = []
    if os.path.isdir(os.path.join(HOME, ".claude")):
        found.append("claude")
    if os.path.isdir(os.path.join(HOME, ".codex")):
        found.append("codex")
    return found or ["claude"]


def register_providers(which):
    providers = ["claude", "codex"] if which == "all" else [which] if which else detect_providers()
    for p in providers:
        print(f"==> Registering provider: {p}")
        _load_adapter(p).register(REPO)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["claude", "codex", "all"], default=None,
                    help="default: auto-detect installed providers")
    args = ap.parse_args()

    make_dirs()
    copy_scripts()
    write_config()
    build_venv()
    download_models()
    warn_portaudio()
    register_providers(args.provider)

    print("\nDone. Restart your provider so the /jarvis* commands appear, then try:")
    print("  /jarvis-on         # speak every reply (this session)")
    print("  /jarvis-off        # silence")
    print("  /jarvis-config     # change voice / speed / engine")


if __name__ == "__main__":
    main()
