import json
from pathlib import Path

from gamenote import config


def test_load_creates_defaults(appdata):
    cfg = config.load_config()
    assert config.config_path().exists()
    assert cfg["version"] == config.CONFIG_VERSION
    assert {p["id"] for p in cfg["profiles"]} == {"editing", "bugs", "daily"}
    assert cfg["global"]["launch_sound"] is True
    assert cfg["global"]["auto_update"] is True
    assert cfg["global"]["language"] == "en"
    assert cfg["global"]["device"] == "auto"
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


def test_example_config_matches_defaults():
    """config.example.json must mirror DEFAULT_CONFIG's key shape, so a new
    config key can't land in one and be forgotten in the other (values may differ,
    e.g. the example's literal dest_root)."""
    example_path = Path(__file__).resolve().parents[1] / "config.example.json"
    example = json.loads(example_path.read_text(encoding="utf-8"))

    def shape(obj):
        if isinstance(obj, dict):
            return {k: shape(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [shape(v) for v in obj]
        return None  # leaf value ignored; only keys/structure matter

    assert shape(example) == shape(config.DEFAULT_CONFIG)
    # explicit guards for the keys recent features added
    assert "device" in example["global"]
    assert all("clip_from_file" in p and "clip_file" in p for p in example["profiles"])
