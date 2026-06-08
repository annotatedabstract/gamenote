import datetime
import json

from gamenote.profiles import (
    LineFormat,
    Profile,
    format_offset,
    read_context,
    sanitize_part,
    validate_profiles,
)


def _obs_sidecar(tmp_path, **fields):
    """Write a gamenote-obs.json sidecar and return its path."""
    f = tmp_path / "gamenote-obs.json"
    f.write_text(json.dumps(fields), encoding="utf-8")
    return f


def test_to_from_dict_roundtrip():
    p = Profile.from_dict({
        "id": "e", "name": "E", "hotkey": "alt+f1",
        "dest_root": r"C:\notes", "path_template": "{context}.md",
    })
    d = p.to_dict()
    assert Profile.from_dict(d).to_dict() == d
    assert "session_from_file" in d and "session_file" in d and "hotkey_beep" in d
    assert "clip_from_file" in d and "clip_file" in d
    assert d["capture_mode"] == "vad"  # default
    assert Profile.from_dict({"capture_mode": "toggle"}).capture_mode == "toggle"
    assert Profile.from_dict({"capture_mode": "weird"}).capture_mode == "vad"  # invalid -> vad


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


def test_validate_allows_relative_template():
    ok = Profile("c", "C", "f3", "d", r"{context}\notes.md")
    assert validate_profiles([ok]) == []


def test_validate_flags_unsafe_path_templates():
    absolute = Profile("a", "A", "f1", "d", r"C:\evil.md")
    traversal = Profile("b", "B", "f2", "d2", r"..\secrets.md")
    errors = validate_profiles([absolute, traversal])
    assert any("relative" in e.lower() for e in errors)
    assert any(".." in e for e in errors)


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


# --- recording-position ({clip}) feature ---------------------------------


def test_format_offset_auto():
    assert format_offset(0) == "00:00"
    assert format_offset(47) == "00:47"
    assert format_offset(6 * 60 + 12) == "06:12"
    assert format_offset(60 * 60 + 3 * 60 + 45) == "1:03:45"  # past an hour
    assert format_offset(-5) == "00:00"  # negative clamps


def test_clip_offset_from_sidecar(tmp_path):
    f = _obs_sidecar(tmp_path, file_start="2026-06-08_14-16-55", recording=True)
    p = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(f))
    now = datetime.datetime(2026, 6, 8, 14, 23, 7)  # 6:12 into the segment
    assert p.clip_offset(now) == "06:12"


def test_clip_offset_omitted_when_not_recording(tmp_path):
    f = _obs_sidecar(tmp_path, file_start="2026-06-08_14-16-55", recording=False)
    p = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(f))
    assert p.clip_offset(datetime.datetime(2026, 6, 8, 14, 23, 7)) == ""


def test_clip_offset_omitted_when_disabled_or_missing(tmp_path):
    disabled = Profile("e", "E", "f1", "d", "x.md",
                       clip_from_file=False, clip_file=str(tmp_path / "x.json"))
    assert disabled.clip_offset() == ""
    missing = Profile("e", "E", "f1", "d", "x.md",
                      clip_from_file=True, clip_file=str(tmp_path / "missing.json"))
    assert missing.clip_offset() == ""


def test_clip_offset_negative_is_omitted(tmp_path):
    f = _obs_sidecar(tmp_path, file_start="2026-06-08_14-16-55", recording=True)
    p = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(f))
    before = datetime.datetime(2026, 6, 8, 14, 10, 0)  # earlier than file_start
    assert p.clip_offset(before) == ""


def test_render_line_with_clip_token(tmp_path):
    f = _obs_sidecar(tmp_path, file_start="2026-06-08_14-16-55", recording=True)
    p = Profile("e", "E", "f1", "d", "x.md",
                LineFormat("%Y-%m-%d %H:%M:%S", "[{clip}] "),
                clip_from_file=True, clip_file=str(f))
    now = datetime.datetime(2026, 6, 8, 14, 23, 7)
    assert p.render_line("note text", now) == "- [2026-06-08 14:23:07] [06:12] note text\n"


def test_render_line_omits_empty_clip_token(tmp_path):
    f = _obs_sidecar(tmp_path, recording=False)  # no live position
    p = Profile("e", "E", "f1", "d", "x.md",
                LineFormat("%Y-%m-%d %H:%M:%S", "[{clip}] "),
                clip_from_file=True, clip_file=str(f))
    now = datetime.datetime(2026, 6, 8, 14, 23, 7)
    # the {clip} token and its now-empty [] wrapper are removed
    assert p.render_line("note text", now) == "- [2026-06-08 14:23:07] note text\n"


def test_render_line_clip_alongside_other_prefix(tmp_path):
    p = Profile("b", "Bugs", "f2", "d", "x.md",
                LineFormat("%H:%M:%S", "[bug] [{clip}] "),
                clip_from_file=True, clip_file=str(tmp_path / "missing.json"))
    now = datetime.datetime(2026, 6, 8, 1, 2, 3)
    # missing sidecar -> {clip} omitted, the literal [bug] prefix is preserved
    assert p.render_line("x", now) == "- [01:02:03] [bug] x\n"


def test_render_line_accepts_injected_clip():
    p = Profile("e", "E", "f1", "d", "x.md", LineFormat("%H:%M:%S", "[{clip}] "))
    now = datetime.datetime(2026, 6, 8, 1, 2, 3)
    assert p.render_line("x", now, clip="1:03:45") == "- [01:02:03] [1:03:45] x\n"


def test_session_header_from_json_sidecar(tmp_path):
    f = _obs_sidecar(tmp_path, session_start="2026-05-31_14-02-10",
                     file_start="2026-05-31_14-20-00", recording=True)
    p = Profile("e", "E", "f1", "d", "x.md", session_from_file=True, session_file=str(f))
    assert p.session_header_value() == "2026-05-31_14-02-10"


def test_read_context_from_json_sidecar(tmp_path):
    f = _obs_sidecar(tmp_path, game="Hollow Knight", session_start="2026-05-31_14-02-10")
    assert read_context({"source": "file", "file_path": str(f)}) == "Hollow Knight"
