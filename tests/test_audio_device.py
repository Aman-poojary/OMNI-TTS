#!/usr/bin/env python3
"""Regression tests for audio._resolve_output. Stdlib-only:

    python3 tests/test_audio_device.py

Locks down output-device selection. The daemon plays to the system default,
which on macOS can be a Bluetooth headset that's silently in call/HFP mode —
so the reply "plays" (full duration) but nothing is heard. Pinning
output_device to a reliable device (e.g. "MacBook Pro Speakers") must resolve
by name substring or index, and fall back to the system default when unset or
unmatched. sounddevice is stubbed so this runs without the venv/hardware.
"""

import os
import sys
import types

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
)

# Stub sounddevice before importing audio.
DEVICES = [
    {"name": "LG ULTRAGEAR", "max_output_channels": 2, "default_samplerate": 48000},
    {"name": "OnePlus Buds 4", "max_output_channels": 2, "default_samplerate": 44100},
    {"name": "Brio 100", "max_output_channels": 0, "default_samplerate": 48000},  # input-only
    {"name": "MacBook Pro Speakers", "max_output_channels": 2, "default_samplerate": 48000},
]
sd = types.ModuleType("sounddevice")


def query_devices(device=None, kind=None):
    if device is None:  # default output when kind=="output", else full list
        return DEVICES[1] if kind == "output" else DEVICES
    return DEVICES[device]


sd.query_devices = query_devices
sys.modules["sounddevice"] = sd

import audio  # noqa: E402


def check(name, cond):
    print(("PASS" if cond else "FAIL") + f"  {name}")
    return cond


def main():
    ok = True
    ok &= check("empty -> system default (None)", audio._resolve_output("") is None)
    ok &= check("None -> system default (None)", audio._resolve_output(None) is None)
    ok &= check("exact name matches", audio._resolve_output("MacBook Pro Speakers") == 3)
    ok &= check("case-insensitive substring matches", audio._resolve_output("macbook") == 3)
    ok &= check("other device by name", audio._resolve_output("OnePlus") == 1)
    ok &= check("digit string is an index", audio._resolve_output("3") == 3)
    ok &= check("int is an index", audio._resolve_output(0) == 0)
    ok &= check("unmatched name -> default (None)", audio._resolve_output("Nonexistent") is None)
    ok &= check("input-only device is never matched for output",
                audio._resolve_output("Brio") is None)

    ok &= check("device_rate for default is the default device's rate",
                audio.device_rate("") == 44100)
    ok &= check("device_rate for a pinned device", audio.device_rate("macbook") == 48000)
    ok &= check("device_name reflects the pinned device",
                audio.device_name("macbook") == "MacBook Pro Speakers")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
