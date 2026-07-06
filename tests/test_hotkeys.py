import logging

from gamenote import hotkeys
from gamenote.profiles import Profile


def test_build_mapping_skips_empty_and_passes_profile_id():
    got = []
    profiles = [
        Profile("a", "A", "f1", "d", "x.md"),
        Profile("b", "B", "f2", "d", "y.md"),
        Profile("c", "C", "", "d", "z.md"),  # no hotkey -> skipped
    ]
    mapping = hotkeys.build_mapping(profiles, lambda pid: got.append(pid))
    assert set(mapping.keys()) == {"f1", "f2"}
    mapping["f1"]()
    mapping["f2"]()
    assert got == ["a", "b"]


def test_set_mapping_when_paused_does_not_register(monkeypatch):
    calls = []
    monkeypatch.setattr(hotkeys.keyboard, "add_hotkey", lambda *a, **k: calls.append(a))
    manager = hotkeys.HotkeyManager()
    manager.paused = True
    failed = manager.set_mapping({"f1": lambda: None})
    assert failed == []
    assert calls == []  # nothing bound while paused
    assert "f1" in manager._mapping


def test_build_mapping_callback_never_raises(caplog):
    # An exception escaping the callback would kill the keyboard library's
    # single processing thread and silently disable every hotkey.
    def boom(profile_id):
        raise RuntimeError("kaputt")

    mapping = hotkeys.build_mapping([Profile("a", "A", "f1", "d", "x.md")], boom)
    with caplog.at_level(logging.ERROR, logger="gamenote.hotkeys"):
        mapping["f1"]()  # must not raise
    assert "'a'" in caplog.text
    assert "kaputt" in caplog.text  # the traceback lands in the log


def test_rebind_reapplies_mapping(monkeypatch):
    bound = []
    monkeypatch.setattr(hotkeys.keyboard, "add_hotkey", lambda hk, cb: bound.append(hk))
    manager = hotkeys.HotkeyManager()
    manager.register({"f13": lambda: None})
    assert manager.rebind() == []
    assert bound == ["f13", "f13"]


def test_rebind_respects_pause(monkeypatch):
    bound = []
    monkeypatch.setattr(hotkeys.keyboard, "add_hotkey", lambda hk, cb: bound.append(hk))
    manager = hotkeys.HotkeyManager()
    manager.register({"f13": lambda: None})
    manager.pause()
    assert manager.rebind() == []
    assert bound == ["f13"]  # nothing new bound while paused
    assert manager.paused


# --- watchdog ---------------------------------------------------------------


class _FakeThread:
    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class _FakeListener:
    def __init__(self, listening_alive: bool = True, processing_alive: bool = True) -> None:
        self.listening_thread = _FakeThread(listening_alive)
        self.processing_thread = _FakeThread(processing_alive)


def test_watchdog_healthy_listener_does_nothing(monkeypatch):
    monkeypatch.setattr(hotkeys.keyboard, "_listener", _FakeListener())
    notes = []
    dog = hotkeys.ListenerWatchdog(hotkeys.HotkeyManager(), notify=notes.append)
    assert dog.check() is False
    assert notes == []


def test_watchdog_ignores_never_started_listener(monkeypatch):
    # Before the first registration the listener has no thread attributes.
    monkeypatch.setattr(hotkeys.keyboard, "_listener", object())
    dog = hotkeys.ListenerWatchdog(hotkeys.HotkeyManager(), notify=lambda _t: None)
    assert dog.check() is False


def test_watchdog_recovers_dead_processing_thread(monkeypatch):
    monkeypatch.setattr(hotkeys.keyboard, "_listener", _FakeListener(processing_alive=False))
    created = []

    def factory():
        listener = _FakeListener()
        created.append(listener)
        return listener

    monkeypatch.setattr(hotkeys.keyboard, "_KeyboardListener", factory)
    monkeypatch.setattr(hotkeys.keyboard, "_pressed_events", {42: "stale key-down"})
    bound = []
    monkeypatch.setattr(hotkeys.keyboard, "add_hotkey", lambda hk, cb: bound.append(hk))
    manager = hotkeys.HotkeyManager()
    manager.register({"f13": lambda: None})
    bound.clear()

    notes = []
    dog = hotkeys.ListenerWatchdog(manager, notify=notes.append)
    assert dog.check() is True
    assert hotkeys.keyboard._listener is created[0]  # fresh listener installed
    assert hotkeys.keyboard._pressed_events == {}  # stale pressed state cleared
    assert bound == ["f13"]  # mapping re-bound
    assert notes == []  # recovered: nothing to nag about
    assert dog.check() is False  # healthy again


def test_watchdog_unrecoverable_death_notifies_once(monkeypatch):
    monkeypatch.setattr(hotkeys.keyboard, "_listener", _FakeListener(listening_alive=False))
    monkeypatch.setattr(hotkeys.keyboard, "_pressed_events", {})

    def broken():
        raise RuntimeError("no listener for you")

    monkeypatch.setattr(hotkeys.keyboard, "_KeyboardListener", broken)
    notes = []
    dog = hotkeys.ListenerWatchdog(hotkeys.HotkeyManager(), notify=notes.append)
    assert dog.check() is True
    assert dog.check() is True  # keeps trying on later ticks...
    assert len(notes) == 1  # ...but tells the user only once
    assert "restart" in notes[0]


def test_watchdog_recovery_respects_pause(monkeypatch):
    monkeypatch.setattr(hotkeys.keyboard, "_listener", _FakeListener(processing_alive=False))
    monkeypatch.setattr(hotkeys.keyboard, "_KeyboardListener", _FakeListener)
    monkeypatch.setattr(hotkeys.keyboard, "_pressed_events", {})
    bound = []
    monkeypatch.setattr(hotkeys.keyboard, "add_hotkey", lambda hk, cb: bound.append(hk))
    manager = hotkeys.HotkeyManager()
    manager.register({"f13": lambda: None})
    manager.pause()
    bound.clear()

    notes = []
    dog = hotkeys.ListenerWatchdog(manager, notify=notes.append)
    assert dog.check() is True
    assert bound == []  # paused: the mapping binds on resume, not here
    assert notes == []  # a clean recovery, no balloon
    assert manager.paused


def test_watchdog_disables_itself_on_unfamiliar_internals(monkeypatch, caplog):
    class Weird:
        processing_thread = object()  # no is_alive(): a future keyboard version

    monkeypatch.setattr(hotkeys.keyboard, "_listener", Weird())
    notes = []
    dog = hotkeys.ListenerWatchdog(hotkeys.HotkeyManager(), notify=notes.append)
    with caplog.at_level(logging.ERROR, logger="gamenote.hotkeys"):
        assert dog.check() is False
        assert dog.check() is False
    assert notes == []
    assert caplog.text.count("disabling") == 1  # logged once, then stands down
