import wave

import numpy as np

from gamenote import sounds


def _write_wav(path, rate=8000, frames=100):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.zeros(frames, dtype=np.int16).tobytes())


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


def test_load_wav_mono_float32(tmp_path):
    wav = tmp_path / "a.wav"
    _write_wav(wav, rate=8000, frames=120)
    data, rate = sounds._load_wav(str(wav))
    assert rate == 8000
    assert data.dtype == np.float32
    assert len(data) == 120


def test_play_uses_custom_file(monkeypatch, tmp_path):
    wav = tmp_path / "b.wav"
    _write_wav(wav, rate=16000, frames=64)
    played = {}
    monkeypatch.setattr(
        sounds.sd, "play", lambda data, rate, **k: played.update(rate=rate, n=len(data))
    )
    sounds.play_arming(str(wav))
    assert played == {"rate": 16000, "n": 64}


def test_play_falls_back_when_file_bad(monkeypatch, tmp_path):
    played = {}
    monkeypatch.setattr(sounds.sd, "play", lambda data, rate, **k: played.update(n=len(data)))
    sounds.play_arming(str(tmp_path / "missing.wav"))
    assert played["n"] == len(sounds._ARMING)  # fell back to the synthesized tone
