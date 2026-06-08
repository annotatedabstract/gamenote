import datetime

from gamenote import notes
from gamenote.profiles import LineFormat, Profile


def test_append_writes_title_header_and_line(tmp_path):
    now = datetime.datetime(2026, 6, 7, 14, 8, 22)
    p = Profile("e", "Editing", "f1", str(tmp_path), "{context}_notes.md",
                LineFormat("%Y-%m-%d %H:%M:%S", ""), use_session_headers=True)
    path = notes.append_note(p, "Octopath", "callback to the cold open", now)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Octopath notes")
    assert "## Recording session: 2026-06-07" in text
    assert "- [2026-06-07 14:08:22] callback to the cold open" in text


def test_header_written_only_when_value_changes(tmp_path):
    p = Profile("e", "E", "f1", str(tmp_path), "log.md",
                LineFormat("%H:%M:%S", ""), use_session_headers=True)
    notes.append_note(p, "", "a", datetime.datetime(2026, 6, 7, 10, 0, 0))
    notes.append_note(p, "", "b", datetime.datetime(2026, 6, 7, 11, 0, 0))  # same date
    notes.append_note(p, "", "c", datetime.datetime(2026, 6, 8, 9, 0, 0))   # new date
    text = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert text.count("## Recording session:") == 2


def test_flat_profile_has_no_headers(tmp_path):
    p = Profile("b", "Bugs", "f2", str(tmp_path), "bugs.md",
                LineFormat("%Y-%m-%d %H:%M:%S", "[bug] "), use_session_headers=False)
    path = notes.append_note(p, "", "crash on load", datetime.datetime(2026, 6, 7, 1, 2, 3))
    text = path.read_text(encoding="utf-8")
    assert "## Recording session" not in text
    assert text.startswith("# Bugs")
    assert "[bug] crash on load" in text


def test_session_header_from_file_value(tmp_path):
    sess = tmp_path / ".current_session"
    sess.write_text("2026-05-31_14-02-10", encoding="utf-8")
    p = Profile("e", "E", "f1", str(tmp_path), "{context}_notes.md",
                LineFormat("%Y-%m-%d %H:%M:%S", ""), use_session_headers=True,
                session_from_file=True, session_file=str(sess))
    path = notes.append_note(p, "Octopath", "x", datetime.datetime(2026, 6, 7, 9, 0, 0))
    assert "## Recording session: 2026-05-31_14-02-10" in path.read_text(encoding="utf-8")
