from io import BytesIO
import wave

from services.audio_service import (
    COMPLETION_CHIME_SECONDS,
    SAMPLE_RATE,
    ambient_noise,
    completion_chime,
)


def wav_properties(data: bytes) -> tuple[int, int, int]:
    with wave.open(BytesIO(data), "rb") as source:
        return source.getframerate(), source.getnchannels(), source.getnframes()


def test_completion_chime_is_a_three_second_valid_wav() -> None:
    sample_rate, channels, frames = wav_properties(completion_chime())
    assert sample_rate == SAMPLE_RATE
    assert channels == 1
    assert frames == int(SAMPLE_RATE * COMPLETION_CHIME_SECONDS)


def test_all_ambient_noise_options_are_valid_local_wav_audio() -> None:
    for kind in ("white", "pink", "brown"):
        sample_rate, channels, frames = wav_properties(
            ambient_noise(kind, duration_seconds=1)
        )
        assert sample_rate == SAMPLE_RATE
        assert channels == 1
        assert frames == SAMPLE_RATE


def test_default_ambient_loop_is_ninety_seconds() -> None:
    sample_rate, channels, frames = wav_properties(ambient_noise("white"))
    assert sample_rate == SAMPLE_RATE
    assert channels == 1
    assert frames == SAMPLE_RATE * 90
