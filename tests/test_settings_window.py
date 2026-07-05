"""Tests for the settings window's apply flow.

These run against real widgets on Qt's offscreen platform (set in conftest.py),
with every QMessageBox variant monkeypatched so nothing blocks. They cover the
three failure-handling behaviors of ``_apply``: validation refusing bad values
before anything is mutated, rollback of the live config when ``on_apply``
raises, and surfacing hotkeys that failed to register.
"""

import copy

import pytest
from PySide6.QtWidgets import QMessageBox

from gamenote.config import default_config
from gamenote.gui import settings_window as sw


@pytest.fixture
def boxes(monkeypatch):
    """Silence all message boxes and record (kind, title, text) of each."""
    shown = []

    def _record(kind):
        def show(parent, title, text, *a, **k):
            shown.append((kind, title, text))
            return QMessageBox.Yes

        return staticmethod(show)

    monkeypatch.setattr(QMessageBox, "warning", _record("warning"))
    monkeypatch.setattr(QMessageBox, "critical", _record("critical"))
    monkeypatch.setattr(QMessageBox, "information", _record("information"))
    monkeypatch.setattr(QMessageBox, "question", _record("question"))
    return shown


def _make_window(qapp, on_apply):
    cfg = default_config()
    win = sw.SettingsWindow(cfg, on_apply)
    return cfg, win


def test_apply_gathers_widgets_into_cfg_and_calls_on_apply(qapp, boxes):
    applied = []
    cfg, win = _make_window(qapp, lambda profiles: applied.append(profiles) or [])
    try:
        win.beam_size.setValue(3)
        assert win._apply() is True
        assert cfg["global"]["beam_size"] == 3
        assert len(applied) == 1
        assert [p.id for p in applied[0]] == [p["id"] for p in cfg["profiles"]]
        assert boxes == []  # clean apply: no dialogs
    finally:
        win.close()


def test_invalid_min_max_blocks_apply_before_any_mutation(qapp, boxes):
    applied = []
    cfg, win = _make_window(qapp, lambda profiles: applied.append(profiles) or [])
    try:
        before = copy.deepcopy(cfg)
        win.min_seconds.setValue(9.0)
        win.max_seconds.setValue(5.0)
        assert win._apply() is False
        assert applied == []  # on_apply never reached
        assert cfg == before  # nothing written into the live config
        assert any(k == "warning" and "min seconds" in text.lower() for k, _t, text in boxes)
    finally:
        win.close()


def test_empty_model_size_blocks_apply(qapp, boxes):
    applied = []
    cfg, win = _make_window(qapp, lambda profiles: applied.append(profiles) or [])
    try:
        win.model_size.setCurrentText("   ")
        assert win._apply() is False
        assert applied == []
        assert any("model size" in text.lower() for _k, _t, text in boxes)
    finally:
        win.close()


def test_on_apply_exception_rolls_back_the_live_config(qapp, boxes):
    def explode(_profiles):
        raise RuntimeError("disk full")

    cfg, win = _make_window(qapp, explode)
    try:
        global_ref = cfg["global"]  # the controller holds this exact dict
        before = copy.deepcopy(cfg)
        win.beam_size.setValue(7)
        assert win._apply() is False
        assert cfg == before  # fully restored...
        assert cfg["global"] is global_ref  # ...in place, not rebound
        assert any(k == "critical" and "disk full" in text for k, _t, text in boxes)
        # The window still works: fix the callback path and apply again.
        win.on_apply = lambda profiles: []
        assert win._apply() is True
        assert cfg["global"]["beam_size"] == 7
    finally:
        win.close()


def test_failed_hotkeys_are_surfaced_but_apply_succeeds(qapp, boxes):
    cfg, win = _make_window(qapp, lambda profiles: ["ctrl+alt+nope"])
    try:
        assert win._apply() is True  # settings did apply; only the bind failed
        assert any(
            k == "warning" and "ctrl+alt+nope" in text and "Hotkeys" in title
            for k, title, text in boxes
        )
    finally:
        win.close()
