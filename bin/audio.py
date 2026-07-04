"""In-process audio playback with device-rate resampling.

Runs under the venv (numpy, sounddevice, scipy). Replaces the temp-WAV +
``afplay`` path so there is no player-binary dependency, and resamples Kokoro's
24 kHz output to the output device's native rate (fixes choppy Bluetooth/AirPods
playback). Resampling logic ported from jarvis-v3 jarvis/speaker.py::render.
"""

from math import gcd


def _output_device():
    import sounddevice as sd

    dev = sd.default.device
    if isinstance(dev, (list, tuple)):
        return dev[1]
    return dev


def device_rate():
    """Native sample rate of the current output device."""
    import sounddevice as sd

    return int(sd.query_devices(_output_device(), "output")["default_samplerate"])


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
