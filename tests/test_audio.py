import threading

import numpy as np
import pytest

from gamenote import audio, config


class _FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        return np.zeros((n, 1), dtype=np.float32), None


def _global(**over):
    g = config.default_config()["global"]
    g.update(over)
    return g


def test_record_falls_back_to_default_device(monkeypatch):
    seen = []

    def fake_input_stream(*a, device=None, **k):
        seen.append(device)
        if device is not None:
            raise RuntimeError("device gone")
        return _FakeStream()

    monkeypatch.setattr(audio.sd, "InputStream", fake_input_stream)
    out = audio.record(
        threading.Event(),
        _global(input_device=5, start_grace_seconds=0.1, max_seconds=1.0),
    )
    assert out is None  # only silence -> no note, but no error raised
    assert seen == [5, None]  # tried the configured device, then the default


def test_record_raises_when_no_device_works(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no input at all")

    monkeypatch.setattr(audio.sd, "InputStream", boom)
    with pytest.raises(audio.AudioCaptureError):
        audio.record(threading.Event(), _global(input_device=None))


def test_vad_mode_returns_none_for_pure_silence(monkeypatch):
    monkeypatch.setattr(audio.sd, "InputStream", lambda *a, **k: _FakeStream())
    out = audio.record(
        threading.Event(),
        _global(input_device=None, start_grace_seconds=0.1, max_seconds=1.0),
        mode="vad",
    )
    assert out is None  # no speech detected -> accidental press


def test_toggle_mode_records_even_without_speech(monkeypatch):
    monkeypatch.setattr(audio.sd, "InputStream", lambda *a, **k: _FakeStream())
    out = audio.record(
        threading.Event(),
        _global(input_device=None, max_seconds=0.2, min_seconds=0.05),
        mode="toggle",
    )
    assert out is not None  # toggle keeps recording until stop/max, silence included
