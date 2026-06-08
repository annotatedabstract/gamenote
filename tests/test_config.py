import json

from gamenote import config


def test_load_creates_defaults(appdata):
    cfg = config.load_config()
    assert config.config_path().exists()
    assert cfg["version"] == config.CONFIG_VERSION
    assert {p["id"] for p in cfg["profiles"]} == {"editing", "bugs", "daily"}
    assert cfg["global"]["launch_sound"] is True
    assert cfg["global"]["auto_update"] is True
    assert cfg["global"]["language"] == "en"
    assert all(p["capture_mode"] == "vad" for p in cfg["profiles"])


def test_merge_backfills_missing_keys(appdata):
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = {
        "version": 1,
        "global": {"model_size": "base.en"},  # everything else missing
        "profiles": [
            {"id": "x", "name": "X", "hotkey": "f1", "dest_root": "d", "path_template": "x.md"}
        ],
    }
    path.write_text(json.dumps(partial), encoding="utf-8")

    cfg = config.load_config()
    assert cfg["global"]["model_size"] == "base.en"   # user value preserved
    assert cfg["global"]["launch_sound"] is True       # backfilled from defaults
    assert cfg["global"]["auto_update"] is True        # backfilled
    assert cfg["profiles"][0]["id"] == "x"             # user profiles taken as-is


def test_save_roundtrip(appdata):
    cfg = config.default_config()
    cfg["global"]["beam_size"] = 7
    config.save_config(cfg)
    assert config.load_config()["global"]["beam_size"] == 7


def test_default_profile_dict():
    assert config.default_profile_dict("editing")["name"] == "Editing notes"
    assert config.default_profile_dict("nope") is None


def test_default_dest_root_under_documents():
    assert config.default_dest_root().replace("\\", "/").endswith("gamenote")
