import datetime
import json

from gamenote import notes
from gamenote.profiles import LineFormat, Profile


def test_append_writes_title_header_and_line(tmp_path):
    now = datetime.datetime(2026, 6, 7, 14, 8, 22)
    p = Profile(
        "e",
        "Editing",
        "f1",
        str(tmp_path),
        "{context}_notes.md",
        LineFormat("%Y-%m-%d %H:%M:%S", ""),
        use_session_headers=True,
    )
    path = notes.append_note(p, "Octopath", "callback to the cold open", now)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Octopath notes")
    assert "## Recording session: 2026-06-07" in text
    assert "- [2026-06-07 14:08:22] callback to the cold open" in text


def test_header_written_only_when_value_changes(tmp_path):
    p = Profile(
        "e",
        "E",
        "f1",
        str(tmp_path),
        "log.md",
        LineFormat("%H:%M:%S", ""),
        use_session_headers=True,
    )
    notes.append_note(p, "", "a", datetime.datetime(2026, 6, 7, 10, 0, 0))
    notes.append_note(p, "", "b", datetime.datetime(2026, 6, 7, 11, 0, 0))  # same date
    notes.append_note(p, "", "c", datetime.datetime(2026, 6, 8, 9, 0, 0))  # new date
    text = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert text.count("## Recording session:") == 2


def test_flat_profile_has_no_headers(tmp_path):
    p = Profile(
        "b",
        "Bugs",
        "f2",
        str(tmp_path),
        "bugs.md",
        LineFormat("%Y-%m-%d %H:%M:%S", "[bug] "),
        use_session_headers=False,
    )
    path = notes.append_note(p, "", "crash on load", datetime.datetime(2026, 6, 7, 1, 2, 3))
    text = path.read_text(encoding="utf-8")
    assert "## Recording session" not in text
    assert text.startswith("# Bugs")
    assert "[bug] crash on load" in text


def test_session_header_from_obs_sidecar(tmp_path):
    sidecar = tmp_path / "gamenote-obs.json"
    sidecar.write_text(
        json.dumps({"session_start": "2026-05-31_14-02-10", "recording": True}),
        encoding="utf-8",
    )
    p = Profile(
        "e",
        "E",
        "f1",
        str(tmp_path),
        "{context}_notes.md",
        LineFormat("%Y-%m-%d %H:%M:%S", ""),
        use_session_headers=True,
        clip_from_file=True,
        clip_file=str(sidecar),
    )
    path = notes.append_note(p, "Octopath", "x", datetime.datetime(2026, 6, 7, 9, 0, 0))
    assert "## Recording session: 2026-05-31_14-02-10" in path.read_text(encoding="utf-8")


def test_append_stamps_clip_offset_from_sidecar(tmp_path):
    sidecar = tmp_path / "gamenote-obs.json"
    sidecar.write_text(
        json.dumps({"file_start": "2026-06-08_14-16-55", "recording": True}),
        encoding="utf-8",
    )
    p = Profile(
        "e",
        "E",
        "f1",
        str(tmp_path),
        "notes.md",
        LineFormat("%Y-%m-%d %H:%M:%S", "[{clip}] "),
        use_session_headers=False,
        clip_from_file=True,
        clip_file=str(sidecar),
    )
    path = notes.append_note(
        p, "", "enemy clips through wall", datetime.datetime(2026, 6, 8, 14, 23, 7)
    )
    text = path.read_text(encoding="utf-8")
    assert "- [2026-06-08 14:23:07] [06:12] enemy clips through wall" in text


def _clip_profile(tmp_path, sidecar, **overrides):
    """A session-headered profile stamping clip offsets from ``sidecar``."""
    kwargs = dict(
        use_session_headers=True,
        clip_from_file=True,
        clip_file=str(sidecar),
    )
    kwargs.update(overrides)
    return Profile(
        "e",
        "E",
        "f1",
        str(tmp_path),
        "{context}_notes.md",
        LineFormat("%Y-%m-%d %H:%M:%S", "[{clip}] "),
        **kwargs,
    )


def test_append_writes_recording_file_subheader(tmp_path):
    sidecar = tmp_path / "gamenote-obs.json"
    sidecar.write_text(
        json.dumps(
            {
                "file_start": "2026-06-08_14-16-55",
                "file_path": "N:\\Recordings\\2026-06-08 14-02-10.mkv",
                "recording": True,
            }
        ),
        encoding="utf-8",
    )
    p = _clip_profile(tmp_path, sidecar)
    path = notes.append_note(
        p, "Octopath", "enemy clips through wall", datetime.datetime(2026, 6, 8, 14, 23, 7)
    )
    assert path.read_text(encoding="utf-8") == (
        "# Octopath notes\n"
        "\n"
        "## Recording session: 2026-06-08\n"
        "\n"
        "### Recording file: 2026-06-08 14-02-10.mkv\n"
        "\n"
        "- [2026-06-08 14:23:07] [06:12] enemy clips through wall\n"
    )


def test_file_subheader_repeats_after_obs_split(tmp_path):
    sidecar = tmp_path / "gamenote-obs.json"
    sidecar.write_text(
        json.dumps(
            {"file_start": "2026-06-08_14-16-55", "file_path": "N:\\rec\\A.mkv", "recording": True}
        ),
        encoding="utf-8",
    )
    p = _clip_profile(tmp_path, sidecar)
    notes.append_note(p, "Octopath", "first note", datetime.datetime(2026, 6, 8, 14, 23, 7))
    sidecar.write_text(
        json.dumps(
            {"file_start": "2026-06-08_14-32-11", "file_path": "N:\\rec\\B.mkv", "recording": True}
        ),
        encoding="utf-8",
    )
    path = notes.append_note(
        p, "Octopath", "note after the split", datetime.datetime(2026, 6, 8, 14, 35, 0)
    )
    text = path.read_text(encoding="utf-8")
    assert text.count("## Recording session:") == 1
    assert text.count("### Recording file:") == 2
    assert (
        text.index("### Recording file: A.mkv")
        < text.index("first note")
        < text.index("### Recording file: B.mkv")
        < text.index("note after the split")
    )


def test_file_subheader_written_once_for_same_file(tmp_path):
    sidecar = tmp_path / "gamenote-obs.json"
    sidecar.write_text(
        json.dumps(
            {"file_start": "2026-06-08_14-16-55", "file_path": "N:\\rec\\A.mkv", "recording": True}
        ),
        encoding="utf-8",
    )
    p = _clip_profile(tmp_path, sidecar)
    notes.append_note(p, "Octopath", "a", datetime.datetime(2026, 6, 8, 14, 23, 7))
    path = notes.append_note(p, "Octopath", "b", datetime.datetime(2026, 6, 8, 14, 25, 0))
    text = path.read_text(encoding="utf-8")
    assert text.count("### Recording file:") == 1


def test_no_file_subheader_when_not_recording(tmp_path):
    sidecar = tmp_path / "gamenote-obs.json"
    sidecar.write_text(
        json.dumps(
            {"file_start": "2026-06-08_14-16-55", "file_path": "N:\\rec\\A.mkv", "recording": False}
        ),
        encoding="utf-8",
    )
    p = _clip_profile(tmp_path, sidecar)
    path = notes.append_note(
        p, "Octopath", "between recordings", datetime.datetime(2026, 6, 8, 14, 23, 7)
    )
    text = path.read_text(encoding="utf-8")
    assert "### Recording file" not in text
    assert "- [2026-06-08 14:23:07] between recordings" in text  # no [clip] either


def test_no_file_subheader_without_session_headers(tmp_path):
    sidecar = tmp_path / "gamenote-obs.json"
    sidecar.write_text(
        json.dumps(
            {"file_start": "2026-06-08_14-16-55", "file_path": "N:\\rec\\A.mkv", "recording": True}
        ),
        encoding="utf-8",
    )
    p = _clip_profile(tmp_path, sidecar, use_session_headers=False)
    path = notes.append_note(p, "Octopath", "flat note", datetime.datetime(2026, 6, 8, 14, 23, 7))
    text = path.read_text(encoding="utf-8")
    assert "### Recording file" not in text
    assert "- [2026-06-08 14:23:07] [06:12] flat note" in text  # clip still stamped


def test_file_subheader_rewritten_with_new_session(tmp_path):
    sidecar = tmp_path / "gamenote-obs.json"
    sidecar.write_text(
        json.dumps(
            {"file_start": "2026-06-08_14-16-55", "file_path": "N:\\rec\\A.mkv", "recording": True}
        ),
        encoding="utf-8",
    )
    p = _clip_profile(tmp_path, sidecar)
    notes.append_note(p, "Octopath", "a", datetime.datetime(2026, 6, 8, 14, 23, 7))
    path = notes.append_note(p, "Octopath", "b", datetime.datetime(2026, 6, 9, 0, 5, 0))
    text = path.read_text(encoding="utf-8")
    assert text.count("## Recording session:") == 2
    assert text.count("### Recording file: A.mkv") == 2


def test_no_file_subheader_when_file_path_empty(tmp_path):
    sidecar = tmp_path / "gamenote-obs.json"
    sidecar.write_text(
        json.dumps({"file_start": "2026-06-08_14-16-55", "file_path": "", "recording": True}),
        encoding="utf-8",
    )
    p = _clip_profile(tmp_path, sidecar)
    path = notes.append_note(p, "Octopath", "early note", datetime.datetime(2026, 6, 8, 14, 23, 7))
    text = path.read_text(encoding="utf-8")
    assert "### Recording file" not in text
    assert "- [2026-06-08 14:23:07] [06:12] early note" in text  # clip still stamped
