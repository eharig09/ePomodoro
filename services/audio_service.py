from __future__ import annotations

from functools import lru_cache
from io import BytesIO
import wave

import numpy as np


SAMPLE_RATE = 16_000
COMPLETION_CHIME_SECONDS = 3.0


def _wav_bytes(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    normalized = np.clip(samples, -1.0, 1.0)
    pcm = (normalized * 32767).astype("<i2")
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())
    return buffer.getvalue()


@lru_cache(maxsize=1)
def completion_chime() -> bytes:
    duration = COMPLETION_CHIME_SECONDS
    timeline = np.arange(int(SAMPLE_RATE * duration)) / SAMPLE_RATE
    envelope = np.exp(-1.05 * timeline)
    fade_in = np.minimum(1.0, timeline / 0.03)
    fade_out = np.clip((duration - timeline) / 0.6, 0.0, 1.0)
    first = np.sin(2 * np.pi * 523.25 * timeline)
    second = np.sin(2 * np.pi * 659.25 * timeline)
    chime = (
        0.2125
        * (0.55 * first + 0.45 * second)
        * envelope
        * fade_in
        * fade_out
    )
    return _wav_bytes(chime)


@lru_cache(maxsize=6)
def ambient_noise(kind: str, duration_seconds: int = 90) -> bytes:
    noise_kind = kind.lower()
    if noise_kind not in {"white", "pink", "brown"}:
        raise ValueError(f"Unsupported noise type: {kind}")

    sample_count = SAMPLE_RATE * duration_seconds
    rng = np.random.default_rng(20260810)
    white = rng.normal(0.0, 1.0, sample_count)

    if noise_kind == "white":
        samples = white
    else:
        spectrum = np.fft.rfft(white)
        frequencies = np.fft.rfftfreq(sample_count, d=1 / SAMPLE_RATE)
        frequencies[0] = frequencies[1]
        exponent = 0.5 if noise_kind == "pink" else 1.0
        samples = np.fft.irfft(spectrum / np.power(frequencies, exponent), sample_count)

    samples -= samples.mean()
    rms = float(np.sqrt(np.mean(np.square(samples)))) or 1.0
    samples = samples / rms * 0.055
    return _wav_bytes(samples)
