"""Short audio cues, synthesized at import and played through sounddevice.

No asset files and no new dependency (sounddevice/PortAudio is already bundled).
Playback is best-effort: if there is no output device it is logged and ignored,
never breaking capture.

- ``play_arming()``: a short ascending chime when the app is ready (armed).
- ``play_hotkey_beep()``: a quiet, very short blip when a hotkey is accepted.
"""

from __future__ import annotations

import logging

import numpy as np
import sounddevice as sd

log = logging.getLogger("gamenote.sounds")

_SR = 44100


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
_ARMING = np.concatenate([
    _tone(523.25, 0.09, 0.22),
    _silence(0.02),
    _tone(659.25, 0.09, 0.22),
    _silence(0.02),
    _tone(783.99, 0.13, 0.24),
]).astype(np.float32)

# Hotkey: a single quiet, short blip.
_BEEP = _tone(880.0, 0.055, 0.12)


def _play(samples: np.ndarray) -> None:
    try:
        sd.play(samples, _SR, blocking=False)
    except Exception as e:  # no output device, etc.
        log.debug("Could not play sound: %s", e)


def play_arming() -> None:
    _play(_ARMING)


def play_hotkey_beep() -> None:
    _play(_BEEP)
