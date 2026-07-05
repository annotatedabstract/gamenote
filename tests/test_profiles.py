import datetime
import json

from gamenote import profiles as gn_profiles
from gamenote.profiles import (
    LineFormat,
    Profile,
    format_offset,
    read_context,
    read_sidecar,
    sanitize_part,
    validate_profiles,
)


def _obs_sidecar(tmp_path, **fields):
    """Write a gamenote-obs.json sidecar and return its path."""
    f = tmp_path / "gamenote-obs.json"
    f.write_text(json.dumps(fields), encoding="utf-8")
    return f


def test_to_from_dict_roundtrip():
    p = Profile.from_dict(
        {
            "id": "e",
            "name": "E",
            "hotkey": "alt+f1",
            "dest_root": r"C:\notes",
            "path_template": "{context}.md",
        }
    )
    d = p.to_dict()
    assert Profile.from_dict(d).to_dict() == d
    assert "hotkey_beep" in d
    assert "clip_from_file" in d and "clip_file" in d
    assert d["context_from_obs"] is False  # default off
    assert d["capture_mode"] == "vad"  # default
    assert Profile.from_dict({"capture_mode": "toggle"}).capture_mode == "toggle"
    assert Profile.from_dict({"capture_mode": "weird"}).capture_mode == "vad"  # invalid -> vad


def test_from_dict_ignores_removed_legacy_keys():
    # Configs from before 1.4.0 carry the removed session-file keys; they must
    # load fine and the keys must not survive a round-trip.
    d = {
        "id": "e",
        "name": "E",
        "hotkey": "f1",
        "dest_root": "d",
        "path_template": "x.md",
        "session_from_file": True,
        "session_file": r"N:\Recordings\.current_session",
    }
    p = Profile.from_dict(d)
    out = p.to_dict()
    assert "session_from_file" not in out and "session_file" not in out


def test_resolve_path_tokens_and_sanitization():
    now = datetime.datetime(2026, 6, 7, 14, 8, 22)
    p = Profile(
        "editing", "E", "alt+f1", r"C:\notes", r"{context}\{profile}_{date}_{time}.md", LineFormat()
    )
    s = str(p.resolve_path("Disco: Elysium", now))
    assert "Disco Elysium" in s  # forbidden ':' stripped
    assert "editing" in s
    assert "2026-06-07" in s and "14-08-22" in s


def test_resolve_path_empty_context_uses_placeholder():
    p = Profile("e", "E", "f1", r"C:\n", "{context}.md", LineFormat())
    assert "_Unsorted" in str(p.resolve_path("", None))


def test_sanitize_part():
    assert sanitize_part("Game: X/Y") == "Game XY"
    assert sanitize_part("trailing.  ") == "trailing"
    assert sanitize_part('a<b>:c"|?*') == "abc"


def test_sanitize_part_guards_reserved_names():
    assert sanitize_part("CON") == "_CON"
    assert sanitize_part("nul.md") == "_nul.md"
    assert sanitize_part("Console") == "Console"  # not reserved


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


def test_session_header_from_clip_sidecar(tmp_path):
    f = _obs_sidecar(
        tmp_path,
        session_start="2026-05-31_14-02-10",
        file_start="2026-05-31_14-20-00",
        recording=True,
    )
    p = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(f))
    assert p.session_header_value() == "2026-05-31_14-02-10"


def test_session_header_falls_back_to_date(tmp_path):
    now = datetime.datetime(2026, 6, 7, 0, 0, 0)
    # clip option off
    off = Profile("e", "E", "f1", "d", "x.md")
    assert off.session_header_value(now) == "2026-06-07"
    # sidecar missing
    missing = Profile(
        "e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(tmp_path / "missing")
    )
    assert missing.session_header_value(now) == "2026-06-07"
    # sidecar without a session_start
    no_start = _obs_sidecar(tmp_path, file_start="2026-06-07_10-00-00", recording=True)
    p = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(no_start))
    assert p.session_header_value(now) == "2026-06-07"


def test_session_header_date_when_not_recording(tmp_path):
    # A stale sidecar from a finished recording must not keep stamping its old
    # session_start; once recording is false the header reverts to the date.
    f = _obs_sidecar(tmp_path, session_start="2026-05-31_14-02-10", recording=False)
    p = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(f))
    assert p.session_header_value(datetime.datetime(2026, 6, 7, 0, 0, 0)) == "2026-06-07"


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
    disabled = Profile(
        "e", "E", "f1", "d", "x.md", clip_from_file=False, clip_file=str(tmp_path / "x.json")
    )
    assert disabled.clip_offset() == ""
    missing = Profile(
        "e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(tmp_path / "missing.json")
    )
    assert missing.clip_offset() == ""


def test_clip_offset_negative_is_omitted(tmp_path):
    f = _obs_sidecar(tmp_path, file_start="2026-06-08_14-16-55", recording=True)
    p = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(f))
    before = datetime.datetime(2026, 6, 8, 14, 10, 0)  # earlier than file_start
    assert p.clip_offset(before) == ""


def test_recording_file_name_from_sidecar(tmp_path):
    p = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True)
    for path in ("N:\\Recordings\\dE_2.mkv", "N:/Recordings/dE_2.mkv", "dE_2.mkv"):
        f = _obs_sidecar(tmp_path, file_path=path, recording=True)
        p.clip_file = str(f)
        assert p.recording_file_name() == "dE_2.mkv"


def test_recording_file_name_omitted_when_not_recording(tmp_path):
    f = _obs_sidecar(tmp_path, file_path="N:\\Recordings\\dE_2.mkv", recording=False)
    p = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(f))
    assert p.recording_file_name() == ""


def test_recording_file_name_omitted_when_disabled_missing_or_blank(tmp_path):
    f = _obs_sidecar(tmp_path, file_path="N:\\Recordings\\dE_2.mkv", recording=True)
    disabled = Profile("e", "E", "f1", "d", "x.md", clip_from_file=False, clip_file=str(f))
    assert disabled.recording_file_name() == ""
    missing = Profile(
        "e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(tmp_path / "missing.json")
    )
    assert missing.recording_file_name() == ""
    no_path = _obs_sidecar(tmp_path, file_start="2026-06-08_14-16-55", recording=True)
    blank = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(no_path))
    assert blank.recording_file_name() == ""


def test_recording_file_name_non_json_file(tmp_path):
    # A clip_file pointing at something that isn't the JSON sidecar is ignored.
    f = tmp_path / "notes.txt"
    f.write_text("2026-05-31_14-02-10", encoding="utf-8")
    p = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file=str(f))
    assert p.recording_file_name() == ""


def test_render_line_with_clip_token(tmp_path):
    f = _obs_sidecar(tmp_path, file_start="2026-06-08_14-16-55", recording=True)
    p = Profile(
        "e",
        "E",
        "f1",
        "d",
        "x.md",
        LineFormat("%Y-%m-%d %H:%M:%S", "[{clip}] "),
        clip_from_file=True,
        clip_file=str(f),
    )
    now = datetime.datetime(2026, 6, 8, 14, 23, 7)
    assert p.render_line("note text", now) == "- [2026-06-08 14:23:07] [06:12] note text\n"


def test_render_line_omits_empty_clip_token(tmp_path):
    f = _obs_sidecar(tmp_path, recording=False)  # no live position
    p = Profile(
        "e",
        "E",
        "f1",
        "d",
        "x.md",
        LineFormat("%Y-%m-%d %H:%M:%S", "[{clip}] "),
        clip_from_file=True,
        clip_file=str(f),
    )
    now = datetime.datetime(2026, 6, 8, 14, 23, 7)
    # the {clip} token and its now-empty [] wrapper are removed
    assert p.render_line("note text", now) == "- [2026-06-08 14:23:07] note text\n"


def test_render_line_clip_alongside_other_prefix(tmp_path):
    p = Profile(
        "b",
        "Bugs",
        "f2",
        "d",
        "x.md",
        LineFormat("%H:%M:%S", "[bug] [{clip}] "),
        clip_from_file=True,
        clip_file=str(tmp_path / "missing.json"),
    )
    now = datetime.datetime(2026, 6, 8, 1, 2, 3)
    # missing sidecar -> {clip} omitted, the literal [bug] prefix is preserved
    assert p.render_line("x", now) == "- [01:02:03] [bug] x\n"


def test_render_line_accepts_injected_clip():
    p = Profile("e", "E", "f1", "d", "x.md", LineFormat("%H:%M:%S", "[{clip}] "))
    now = datetime.datetime(2026, 6, 8, 1, 2, 3)
    assert p.render_line("x", now, clip="1:03:45") == "- [01:02:03] [1:03:45] x\n"


def test_read_context_from_json_sidecar(tmp_path):
    f = _obs_sidecar(tmp_path, game="Hollow Knight", session_start="2026-05-31_14-02-10")
    assert read_context({"source": "file", "file_path": str(f)}) == "Hollow Knight"


# --- per-profile context from the OBS sidecar ------------------------------

_GLOBAL_CTX = {"source": "manual", "value": "Tray Game", "file_path": ""}


def _obs_ctx_profile(clip_file, **overrides):
    kwargs = {"clip_from_file": True, "clip_file": str(clip_file), "context_from_obs": True}
    kwargs.update(overrides)
    return Profile("e", "E", "f1", "d", "x.md", **kwargs)


def test_effective_context_defaults_to_global(tmp_path):
    f = _obs_sidecar(tmp_path, game="Hollow Knight")
    # no OBS wiring at all
    plain = Profile("e", "E", "f1", "d", "x.md")
    assert plain.effective_context(_GLOBAL_CTX) == "Tray Game"
    # OBS file wired up but the context opt-in unchecked
    no_opt_in = _obs_ctx_profile(f, context_from_obs=False)
    assert no_opt_in.effective_context(_GLOBAL_CTX) == "Tray Game"
    # opt-in checked but the OBS option itself off -> inert
    obs_off = _obs_ctx_profile(f, clip_from_file=False)
    assert obs_off.effective_context(_GLOBAL_CTX) == "Tray Game"


def test_effective_context_reads_game_from_sidecar(tmp_path):
    f = _obs_sidecar(tmp_path, game="  Hollow Knight ", recording=True)
    assert _obs_ctx_profile(f).effective_context(_GLOBAL_CTX) == "Hollow Knight"


def test_effective_context_ignores_recording_flag(tmp_path):
    # Unlike {clip} and the headers, context does not go quiet when recording
    # stops: the sidecar's last game is still the best guess at what is played.
    f = _obs_sidecar(tmp_path, game="Hollow Knight", recording=False)
    assert _obs_ctx_profile(f).effective_context(_GLOBAL_CTX) == "Hollow Knight"


def test_effective_context_override_is_strict(tmp_path):
    # A missing sidecar or one without a game yields "" (-> _Unsorted), not the
    # global context: the override fully replaces it, mirroring the global file
    # source's own semantics.
    missing = _obs_ctx_profile(tmp_path / "missing.json")
    assert missing.effective_context(_GLOBAL_CTX) == ""
    no_game = _obs_sidecar(tmp_path, session_start="2026-05-31_14-02-10", recording=True)
    assert _obs_ctx_profile(no_game).effective_context(_GLOBAL_CTX) == ""


def test_effective_context_plain_text_file(tmp_path):
    # A legacy plain-text .current_game works for the per-profile source too.
    f = tmp_path / ".current_game"
    f.write_text("Cyberpunk\n", encoding="utf-8")
    assert _obs_ctx_profile(f).effective_context(_GLOBAL_CTX) == "Cyberpunk"


def test_effective_context_global_file_source(tmp_path):
    # Without the override, a file-sourced global context flows through.
    f = _obs_sidecar(tmp_path, game="Hollow Knight")
    plain = Profile("e", "E", "f1", "d", "x.md")
    cfg = {"source": "file", "value": "ignored", "file_path": str(f)}
    assert plain.effective_context(cfg) == "Hollow Knight"


# --- sidecar snapshot + mid-write retry -------------------------------------


def test_read_sidecar_parses_json_plain_text_and_missing(tmp_path):
    f = _obs_sidecar(tmp_path, game="Hades", recording=True)
    snap = read_sidecar(str(f))
    assert snap.data == {"game": "Hades", "recording": True}
    assert snap.context_value() == "Hades"

    plain = tmp_path / ".current_game"
    plain.write_text("  Cyberpunk  ", encoding="utf-8")
    snap = read_sidecar(str(plain))
    assert snap.data is None
    assert snap.context_value() == "Cyberpunk"

    missing = read_sidecar(str(tmp_path / "nope.json"))
    assert missing.data is None and missing.text is None
    assert missing.context_value() == ""


def test_read_sidecar_retries_an_empty_mid_write_read(tmp_path, monkeypatch):
    # The OBS script truncates the sidecar in place before writing, so a read
    # can see an empty file. The retry must pick up the finished write.
    f = tmp_path / "gamenote-obs.json"
    f.write_text("", encoding="utf-8")
    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        f.write_text(json.dumps({"game": "Hades"}), encoding="utf-8")

    monkeypatch.setattr(gn_profiles.time, "sleep", fake_sleep)
    snap = read_sidecar(str(f))
    assert slept  # the suspicious read was detected and waited out
    assert snap.data == {"game": "Hades"}


def test_read_sidecar_retries_partial_json(tmp_path, monkeypatch):
    f = tmp_path / "gamenote-obs.json"
    f.write_text('{"game": "Ha', encoding="utf-8")

    def fake_sleep(_seconds):
        f.write_text(json.dumps({"game": "Hades", "recording": True}), encoding="utf-8")

    monkeypatch.setattr(gn_profiles.time, "sleep", fake_sleep)
    assert read_sidecar(str(f)).data == {"game": "Hades", "recording": True}


def test_read_sidecar_plain_text_never_retries(tmp_path, monkeypatch):
    # A plain-text context value is not "suspicious"; it must not pay the
    # retry delay on every read.
    def boom(_seconds):
        raise AssertionError("read_sidecar slept on a plain-text file")

    monkeypatch.setattr(gn_profiles.time, "sleep", boom)
    f = tmp_path / ".current_game"
    f.write_text("Elden Ring", encoding="utf-8")
    assert read_sidecar(str(f)).context_value() == "Elden Ring"


def test_read_sidecar_gives_up_after_one_retry(tmp_path, monkeypatch):
    f = tmp_path / "gamenote-obs.json"
    f.write_text("", encoding="utf-8")
    slept = []
    monkeypatch.setattr(gn_profiles.time, "sleep", lambda s: slept.append(s))
    snap = read_sidecar(str(f))
    assert len(slept) == 1
    assert snap.data is None and snap.text == ""


def test_read_sidecar_keeps_first_read_when_retry_read_fails(tmp_path, monkeypatch):
    # If the file vanishes between the suspicious read and the retry, the
    # first read still stands (no crash, no None-out of data we already had).
    f = tmp_path / "gamenote-obs.json"
    f.write_text('{"game": "Ha', encoding="utf-8")
    monkeypatch.setattr(gn_profiles.time, "sleep", lambda _s: f.unlink())
    snap = read_sidecar(str(f))
    assert snap.data is None
    assert snap.text == '{"game": "Ha'


def test_context_value_never_leaks_a_json_fragment(tmp_path, monkeypatch):
    # A sidecar that stays partially written (retry also sees the fragment)
    # must not turn the fragment into a "game name" (and thus a note path).
    f = tmp_path / "gamenote-obs.json"
    f.write_text('{"game": "Ha', encoding="utf-8")
    monkeypatch.setattr(gn_profiles.time, "sleep", lambda _s: None)
    assert read_sidecar(str(f)).context_value() == ""
    assert read_context({"source": "file", "file_path": str(f)}) == ""


def test_profile_methods_use_the_snapshot_not_the_file(tmp_path):
    # Once a snapshot is taken the methods must not re-read the file: delete it
    # and every OBS-derived value still resolves from the snapshot.
    f = _obs_sidecar(
        tmp_path,
        game="Hollow Knight",
        session_start="2026-06-08_14-00-00",
        file_start="2026-06-08_14-16-55",
        file_path="N:\\Recordings\\dE_2.mkv",
        recording=True,
    )
    p = Profile(
        "e",
        "E",
        "f1",
        "d",
        "x.md",
        clip_from_file=True,
        clip_file=str(f),
        context_from_obs=True,
    )
    snap = p.sidecar_snapshot()
    f.unlink()
    now = datetime.datetime(2026, 6, 8, 14, 23, 7)
    assert p.session_header_value(now, sidecar=snap) == "2026-06-08_14-00-00"
    assert p.clip_offset(now, sidecar=snap) == "06:12"
    assert p.recording_file_name(sidecar=snap) == "dE_2.mkv"
    assert p.effective_context(_GLOBAL_CTX, sidecar=snap) == "Hollow Knight"


def test_sidecar_snapshot_none_when_option_off(tmp_path):
    assert Profile("e", "E", "f1", "d", "x.md").sidecar_snapshot() is None
    no_file = Profile("e", "E", "f1", "d", "x.md", clip_from_file=True, clip_file="")
    assert no_file.sidecar_snapshot() is None
