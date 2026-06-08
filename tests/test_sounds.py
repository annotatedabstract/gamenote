import numpy as np

from gamenote import sounds


def test_cues_are_valid_float32_audio():
    for samples in (sounds._ARMING, sounds._BEEP):
        assert samples.dtype == np.float32
        assert len(samples) > 0
        assert float(np.max(np.abs(samples))) <= 1.0


def test_play_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no output device")
    monkeypatch.setattr(sounds.sd, "play", boom)
    # Must be swallowed, not propagated.
    sounds.play_arming()
    sounds.play_hotkey_beep()
