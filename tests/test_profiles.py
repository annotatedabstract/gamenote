import datetime

from gamenote.profiles import (
    LineFormat,
    Profile,
    read_context,
    sanitize_part,
    validate_profiles,
)


def test_to_from_dict_roundtrip():
    p = Profile.from_dict({
        "id": "e", "name": "E", "hotkey": "alt+f1",
        "dest_root": r"C:\notes", "path_template": "{context}.md",
    })
    d = p.to_dict()
    assert Profile.from_dict(d).to_dict() == d
    assert "session_from_file" in d and "session_file" in d and "hotkey_beep" in d


def test_resolve_path_tokens_and_sanitization():
    now = datetime.datetime(2026, 6, 7, 14, 8, 22)
    p = Profile("editing", "E", "alt+f1", r"C:\notes",
                r"{context}\{profile}_{date}_{time}.md", LineFormat())
    s = str(p.resolve_path("Disco: Elysium", now))
    assert "Disco Elysium" in s          # forbidden ':' stripped
    assert "editing" in s
    assert "2026-06-07" in s and "14-08-22" in s


def test_resolve_path_empty_context_uses_placeholder():
    p = Profile("e", "E", "f1", r"C:\n", "{context}.md", LineFormat())
    assert "_Unsorted" in str(p.resolve_path("", None))


def test_sanitize_part():
    assert sanitize_part("Game: X/Y") == "Game XY"
    assert sanitize_part("trailing.  ") == "trailing"
    assert sanitize_part('a<b>:c"|?*') == "abc"


def test_validate_profiles_flags_dupes_and_empties():
    a = Profile("e", "E", "f1", "d", "x.md")
    b = Profile("e", "", "f1", "", "y.md")  # dup id, dup hotkey, empty name + dest_root
    errors = validate_profiles([a, b])
    assert any("duplicate id" in e for e in errors)
    assert any("hotkey" in e for e in errors)
    assert any("name" in e for e in errors)
    assert any("destination" in e for e in errors)


def test_session_header_from_file(tmp_path):
    f = tmp_path / ".current_session"
    f.write_text("2026-05-31_14-02-10", encoding="utf-8")
    p = Profile("e", "E", "f1", "d", "x.md", session_from_file=True, session_file=str(f))
    assert p.session_header_value() == "2026-05-31_14-02-10"


def test_session_header_falls_back_to_date(tmp_path):
    now = datetime.datetime(2026, 6, 7, 0, 0, 0)
    p = Profile("e", "E", "f1", "d", "x.md",
                session_from_file=True, session_file=str(tmp_path / "missing"))
    assert p.session_header_value(now) == "2026-06-07"


def test_read_context_manual_and_file(tmp_path):
    assert read_context({"source": "manual", "value": "  Hades  "}) == "Hades"
    f = tmp_path / ".current_game"
    f.write_text("Cyberpunk", encoding="utf-8")
    assert read_context({"source": "file", "file_path": str(f)}) == "Cyberpunk"
    assert read_context({"source": "file", "file_path": str(tmp_path / "none")}) == ""
