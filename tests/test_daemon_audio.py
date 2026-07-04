#!/usr/bin/env python3
"""Regression tests for tts_daemon.render_and_play device handling. Stdlib-only:

    python3 tests/test_daemon_audio.py

Locks down the stale-device failure: PortAudio snapshots the device list at
init, so when macOS switched the default output (AirPods/USB) the long-running
daemon raised PortAudioError -9986 opening the stream and dropped the job in
silence. render_and_play must (a) re-enumerate devices before every job,
(b) retry a failed open once, and (c) fall back to system TTS instead of
staying silent when the device never comes up.

The venv-only modules (sounddevice via ``audio``, ``fallback``'s subprocess)
are replaced with in-memory stubs, so this runs under any python3.
"""

import os
import sys
import tempfile
import threading
import types

os.environ["JARVIS_HOME"] = tempfile.mkdtemp(prefix="jarvis-daemon-test-")
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
)


class FakeStream:
    def __init__(self):
        self.written = []
        self.closed = False

    def write(self, wave):
        self.written.append(wave)

    def stop(self):
        pass

    def close(self):
        self.closed = True


def make_audio_stub(fail_opens):
    """An ``audio`` module whose first `fail_opens` open calls raise."""
    stub = types.ModuleType("audio")
    stub.resets = 0
    stub.opens = 0
    stub.streams = []

    def reset():
        stub.resets += 1

    def device_rate(device=None):
        return 48000

    def device_name(device=None):
        return device or "System Default"

    def open_output_stream(rate, channels=1, device=None):
        stub.opens += 1
        if stub.opens <= fail_opens:
            raise RuntimeError("Error opening OutputStream: Internal PortAudio error -9986")
        s = FakeStream()
        stub.streams.append(s)
        return s

    def resample(samples, src, dst):
        return samples

    stub.reset = reset
    stub.device_rate = device_rate
    stub.device_name = device_name
    stub.open_output_stream = open_output_stream
    stub.resample = resample
    return stub


def make_fallback_stub():
    stub = types.ModuleType("fallback")
    stub.spoken = []
    stub.speak = lambda text, voice=None: stub.spoken.append(text) or True
    return stub


class FakeModel:
    def create(self, text, voice=None, speed=1.0):
        return [0.0] * 16, 24000


def make_job(text="All systems nominal, sir."):
    return {
        "id": 1,
        "text": text,
        "voice": "bm_george",
        "speed": 1.0,
        "session": "test-session",
        "abort": threading.Event(),
        "queued_at": 0.0,
    }


def check(name, cond):
    print(("PASS" if cond else "FAIL") + f"  {name}")
    return cond


def run_case(fail_opens):
    audio_stub = make_audio_stub(fail_opens)
    fallback_stub = make_fallback_stub()
    sys.modules["audio"] = audio_stub
    sys.modules["fallback"] = fallback_stub

    import tts_daemon

    tts_daemon.DEVICE_RETRY_SECS = 0.01
    tts_daemon._model = FakeModel()
    tts_daemon.render_and_play(make_job())
    return audio_stub, fallback_stub


def main():
    ok = True

    # Healthy device: devices are re-enumerated before the job, audio plays.
    audio_stub, fallback_stub = run_case(fail_opens=0)
    ok &= check("devices re-enumerated before every job", audio_stub.resets == 1)
    ok &= check("audio played on the stream", len(audio_stub.streams[0].written) > 0)
    ok &= check("stream closed after playback", audio_stub.streams[0].closed)
    ok &= check("no fallback when device is healthy", fallback_stub.spoken == [])

    # Device vanished (stale after a switch): one retry with a fresh list wins.
    audio_stub, fallback_stub = run_case(fail_opens=1)
    ok &= check("failed open retried with a fresh device list",
                audio_stub.resets == 2 and len(audio_stub.streams[0].written) > 0)
    ok &= check("no fallback when the retry succeeds", fallback_stub.spoken == [])

    # Device never comes up: system TTS speaks instead of silence.
    audio_stub, fallback_stub = run_case(fail_opens=2)
    ok &= check("system TTS fallback speaks the reply",
                fallback_stub.spoken == ["All systems nominal, sir."])

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
