"""Short audio cues, synthesized at import and played through sounddevice.

No asset files and no new dependency (sounddevice/PortAudio is already bundled).
Playback is best-effort: if there is no output device it is logged and ignored,
never breaking capture.

- ``play_arming()``: a short ascending chime when the app is ready (armed).
- ``play_hotkey_beep()``: a quiet, very short blip when a hotkey is accepted.
"""

from __future__ import annotations

import logging
import wave

import numpy as np
import sounddevice as sd

log = logging.getLogger("gamenote.sounds")

_SR = 44100
_wav_cache: dict[str, tuple[np.ndarray, int]] = {}


def _load_wav(path: str) -> tuple[np.ndarray, int]:
    """Load a WAV file into a mono float32 array and its sample rate (cached)."""
    if path in _wav_cache:
        return _wav_cache[path]
    with wave.open(path, "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported WAV sample width: {width}")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)  # downmix to mono
    result = (data.astype(np.float32), rate)
    _wav_cache[path] = result
    return result


def _tone(freq: float, dur: float, volume: float, fade: float = 0.008) -> np.ndarray:
    n = int(_SR * dur)
    t = np.arange(n) / _SR
    wave = np.sin(2 * np.pi * freq * t).astype(np.float32)
    nf = max(1, int(_SR * fade))
    if n > 2 * nf:  # fade in/out so there is no click
        env = np.ones(n, dtype=np.float32)
        env[:nf] = np.linspace(0.0, 1.0, nf, dtype=np.float32)
        env[-nf:] = np.linspace(1.0, 0.0, nf, dtype=np.float32)
        wave *= env
    return wave * volume


def _silence(dur: float) -> np.ndarray:
    return np.zeros(int(_SR * dur), dtype=np.float32)


# Arming: a C major arpeggio (C5, E5, G5) that reads as "ready".
_ARMING = np.concatenate(
    [
        _tone(523.25, 0.09, 0.22),
        _silence(0.02),
        _tone(659.25, 0.09, 0.22),
        _silence(0.02),
        _tone(783.99, 0.13, 0.24),
    ]
).astype(np.float32)

# Hotkey: a single quiet, short blip.
_BEEP = _tone(880.0, 0.055, 0.12)


def _play(samples: np.ndarray, sample_rate: int = _SR) -> None:
    try:
        sd.play(samples, sample_rate, blocking=False)
    except Exception as e:  # no output device, etc.
        log.debug("Could not play sound: %s", e)


def _play_file_or(samples: np.ndarray, path: str | None) -> None:
    if path:
        try:
            data, rate = _load_wav(path)
            _play(data, rate)
            return
        except Exception as e:
            log.warning("Could not play custom sound %r (%s); using the default.", path, e)
    _play(samples)


def play_arming(path: str | None = None) -> None:
    _play_file_or(_ARMING, path)


def play_hotkey_beep(path: str | None = None) -> None:
    _play_file_or(_BEEP, path)
