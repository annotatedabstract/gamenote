"""Tests for the recording state machine (Controller).

The hotkey -> on_profile -> worker flow is driven synchronously here: the worker
Thread is replaced with one that runs inline, and audio/transcriber/notes/sounds
are faked, so each overlay-message branch is asserted without real I/O, audio
devices, or an event loop.
"""

import json
import pathlib

from gamenote import audio as gn_audio
from gamenote import controller as gn_controller
from gamenote.controller import Controller
from gamenote.profiles import Profile, SidecarSnapshot

# QObject signals need an application instance; the shared session-scoped
# ``qapp`` fixture (tests/conftest.py) provides it.


class _FakeTranscriber:
    def __init__(self, ready=True, text="hello"):
        self._ready = ready
        self._text = text

    @property
    def ready(self):
        return self._ready

    def transcribe(self, audio):
        return self._text


class _SyncThread:
    """Stand-in for threading.Thread that runs the target inline on start()."""

    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        if self._target:
            self._target(*self._args)


def _make_config():
    return {
        "global": {
            "log_level": "INFO",
            "hotkey_beep_file": "",
            "context": {"value": "", "source": "manual", "file_path": ""},
        }
    }


def _make_profiles():
    return [
        Profile("editing", "Editing", "alt+f1", "d", "x.md"),  # vad
        Profile("push", "Push", "alt+f2", "d", "y.md", capture_mode="toggle"),  # toggle
    ]


def _build(monkeypatch, transcriber, record_result=None, record_exc=None):
    monkeypatch.setattr(gn_controller.threading, "Thread", _SyncThread)
    monkeypatch.setattr(gn_controller.gn_sounds, "play_hotkey_beep", lambda *a, **k: None)

    def fake_record(stop_event, cfg, mode="vad", debug=False):
        if record_exc is not None:
            raise record_exc
        return record_result

    monkeypatch.setattr(gn_controller.gn_audio, "record", fake_record)

    calls = {}

    def fake_append(profile, context, text, now=None, sidecar=None):
        calls["append"] = (profile.id, context, text)
        calls["sidecar"] = sidecar
        return pathlib.Path("note.md")

    monkeypatch.setattr(gn_controller.gn_notes, "append_note", fake_append)

    ctl = Controller(transcriber, _make_profiles(), _make_config())
    msgs = []
    ctl.overlay_message.connect(lambda text, color, persistent, indicator: msgs.append(text))
    return ctl, msgs, calls


def test_not_ready_shows_loading(qapp, monkeypatch):
    ctl, msgs, calls = _build(monkeypatch, _FakeTranscriber(ready=False))
    ctl.on_profile("editing")
    assert ctl.is_recording is False
    assert any("loading" in m for m in msgs)
    assert "append" not in calls


def test_unknown_profile_is_ignored(qapp, monkeypatch):
    ctl, msgs, calls = _build(monkeypatch, _FakeTranscriber())
    ctl.on_profile("nope")
    assert ctl.is_recording is False
    assert "append" not in calls


def test_successful_note_saves_and_resets(qapp, monkeypatch):
    ctl, msgs, calls = _build(monkeypatch, _FakeTranscriber(text="hello"), record_result=object())
    ctl.on_profile("editing")
    assert calls["append"] == ("editing", "", "hello")
    assert ctl.is_recording is False
    assert ctl.active_profile_id is None
    assert ctl.last_note_path is not None
    assert any(m.startswith("saved") for m in msgs)


def test_no_audio_files_nothing(qapp, monkeypatch):
    ctl, msgs, calls = _build(monkeypatch, _FakeTranscriber(), record_result=None)
    ctl.on_profile("editing")
    assert "append" not in calls
    assert any("no note" in m for m in msgs)
    assert ctl.is_recording is False


def test_empty_transcript_files_nothing(qapp, monkeypatch):
    ctl, msgs, calls = _build(monkeypatch, _FakeTranscriber(text=""), record_result=object())
    ctl.on_profile("editing")
    assert "append" not in calls
    assert any("no speech" in m for m in msgs)


def test_mic_error_is_reported(qapp, monkeypatch):
    ctl, msgs, calls = _build(
        monkeypatch, _FakeTranscriber(), record_exc=gn_audio.AudioCaptureError("boom")
    )
    ctl.on_profile("editing")
    assert any("mic error" in m for m in msgs)
    assert ctl.is_recording is False  # finally still resets


def test_worker_exception_is_caught_and_resets(qapp, monkeypatch):
    class _Boom(_FakeTranscriber):
        def transcribe(self, audio):
            raise RuntimeError("kaboom")

    ctl, msgs, calls = _build(monkeypatch, _Boom(), record_result=object())
    ctl.on_profile("editing")
    assert any(m == "error" for m in msgs)
    assert ctl.is_recording is False


def test_busy_press_is_rejected(qapp, monkeypatch):
    ctl, msgs, calls = _build(monkeypatch, _FakeTranscriber(), record_result=object())
    ctl.is_recording = True
    ctl.active_profile_id = "editing"  # a vad recording is in progress
    ctl.on_profile("push")
    assert any("busy" in m for m in msgs)
    assert "append" not in calls


def test_load_failed_shows_model_error(qapp, monkeypatch):
    transcriber = _FakeTranscriber(ready=False)
    transcriber.load_failed = True  # model load exhausted all attempts
    ctl, msgs, calls = _build(monkeypatch, transcriber)
    ctl.on_profile("editing")
    assert any("model error" in m for m in msgs)
    assert not any("loading" in m for m in msgs)


def test_toggle_second_press_signals_stop(qapp, monkeypatch):
    ctl, msgs, calls = _build(monkeypatch, _FakeTranscriber(), record_result=object())
    ctl.is_recording = True
    ctl.active_profile_id = "push"  # push is a toggle profile
    ctl.stop_event.clear()
    ctl.on_profile("push")  # same toggle profile -> request stop
    assert ctl.stop_event.is_set()


def test_worker_takes_one_sidecar_snapshot(qapp, monkeypatch, tmp_path):
    # An OBS-wired profile gets a single snapshot that feeds both the context
    # and the note append (append_note receives it instead of re-reading).
    sidecar = tmp_path / "gamenote-obs.json"
    sidecar.write_text(json.dumps({"game": "Hades", "recording": True}), encoding="utf-8")
    ctl, msgs, calls = _build(monkeypatch, _FakeTranscriber(text="hi"), record_result=object())
    profile = ctl.profiles["editing"]
    profile.clip_from_file = True
    profile.clip_file = str(sidecar)
    profile.context_from_obs = True
    ctl.on_profile("editing")
    assert calls["append"] == ("editing", "Hades", "hi")
    assert isinstance(calls["sidecar"], SidecarSnapshot)
    assert calls["sidecar"].data == {"game": "Hades", "recording": True}


def test_plain_profile_passes_no_snapshot(qapp, monkeypatch):
    ctl, msgs, calls = _build(monkeypatch, _FakeTranscriber(), record_result=object())
    ctl.on_profile("editing")
    assert calls["sidecar"] is None


def test_note_finished_emitted_after_worker(qapp, monkeypatch):
    ctl, msgs, calls = _build(monkeypatch, _FakeTranscriber(), record_result=object())
    done = []
    # Capture the state AT emit time: the app's reload check runs off this
    # signal and must see is_recording already reset.
    ctl.note_finished.connect(lambda: done.append(ctl.is_recording))
    ctl.on_profile("editing")
    assert done == [False]


def test_note_finished_emitted_even_on_error(qapp, monkeypatch):
    ctl, msgs, calls = _build(
        monkeypatch, _FakeTranscriber(), record_exc=gn_audio.AudioCaptureError("boom")
    )
    done = []
    ctl.note_finished.connect(lambda: done.append(ctl.is_recording))
    ctl.on_profile("editing")
    assert done == [False]
