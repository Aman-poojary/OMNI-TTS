#!/usr/bin/env python3
"""Cross-platform uninstaller for JARVIS.

    python uninstall.py

Stops the daemon, unregisters hooks + removes skills for every provider, and
deletes ~/.jarvis/. Provider transcripts/history are never touched.
"""

import importlib.util
import os
import shutil
import urllib.request

REPO = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
JARVIS = os.path.join(HOME, ".jarvis")
PORT = int(os.environ.get("JARVIS_TTS_PORT", "7739"))


def stop_daemon():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/stop", data=b"", timeout=3)
        print("==> Asked daemon to stop")
    except Exception:
        pass


def _load_adapter(provider):
    path = os.path.join(REPO, "adapters", provider, "register.py")
    spec = importlib.util.spec_from_file_location(f"jarvis_adapter_{provider}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    stop_daemon()
    for p in ("claude", "codex"):
        try:
            print(f"==> Unregistering provider: {p}")
            _load_adapter(p).unregister()
        except Exception as e:
            print(f"    ({p}: {e!r})")
    shutil.rmtree(JARVIS, ignore_errors=True)
    print(f"==> Removed {JARVIS}")
    print("Done. Restart your provider to clear the /jarvis* commands.")


if __name__ == "__main__":
    main()
