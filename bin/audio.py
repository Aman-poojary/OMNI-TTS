"""In-process audio playback with device-rate resampling.

Runs under the venv (numpy, sounddevice, scipy). Replaces the temp-WAV +
``afplay`` path so there is no player-binary dependency, and resamples Kokoro's
24 kHz output to the output device's native rate (fixes choppy Bluetooth/AirPods
playback). Resampling logic ported from jarvis-v3 jarvis/speaker.py::render.
"""

from math import gcd


def _resolve_output(device=None):
    """Resolve an output-device spec to a sounddevice index.

    ``None``/``""`` -> the current system default (returns ``None`` so
    sounddevice picks it). An int (or digit string) is used as-is. Any other
    string is matched case-insensitively as a substring against the names of
    output-capable devices (so ``"MacBook Pro Speakers"`` or just ``"macbook"``
    both work). An unmatched name falls back to the system default.
    """
    import sounddevice as sd

    if device is None or device == "":
        return None
    if isinstance(device, int):
        return device
    s = str(device).strip()
    if s.isdigit():
        return int(s)
    needle = s.lower()
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0 and needle in d["name"].lower():
            return i
    return None  # no match: fall back to the system default


def reset():
    """Re-enumerate audio devices.

    PortAudio snapshots the device list when it initializes, so a long-running
    process never sees a default-output change (AirPods pairing, USB audio
    coming/going) and opens streams against a stale device (PaMacCore '!obj',
    error -9986). Terminating and re-initializing re-reads the current list.
    """
    import sounddevice as sd

    sd._terminate()
    sd._initialize()


def _output_info(device=None):
    import sounddevice as sd

    idx = _resolve_output(device)
    return sd.query_devices(kind="output") if idx is None else sd.query_devices(idx, "output")


def device_name(device=None):
    """Human-readable name of the device that would actually be played to."""
    return _output_info(device)["name"]


def device_rate(device=None):
    """Native sample rate of the resolved output device."""
    return int(_output_info(device)["default_samplerate"])


def resample(audio, src_rate, dst_rate):
    """Resample a 1-D float32 waveform from src_rate to dst_rate. No-op if equal."""
    import numpy as np

    if src_rate == dst_rate:
        return audio.astype(np.float32)
    from scipy.signal import resample_poly

    g = gcd(int(dst_rate), int(src_rate))
    up, down = int(dst_rate) // g, int(src_rate) // g
    return resample_poly(audio, up, down).astype(np.float32)


def play(audio, rate):
    """Play a waveform and block until it finishes."""
    import sounddevice as sd

    sd.play(audio, samplerate=rate)
    sd.wait()


def open_output_stream(rate, channels=1, device=None):
    """Open and start a streaming output for producer/consumer playback.

    ``device`` selects the output (see ``_resolve_output``); ``None`` uses the
    system default. Write float32 chunks with ``stream.write(chunk)``;
    ``stream.abort()`` cuts playback immediately (used by /stop). Caller must
    close the stream.
    """
    import sounddevice as sd

    stream = sd.OutputStream(
        samplerate=rate, channels=channels, dtype="float32",
        device=_resolve_output(device),
    )
    stream.start()
    return stream
