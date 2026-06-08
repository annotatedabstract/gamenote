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
