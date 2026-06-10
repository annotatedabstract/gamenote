"""Configuration storage for gamenote.

The single source of truth for runtime settings is a JSON file at
``%APPDATA%\\gamenote\\config.json``. This module owns the schema, the
defaults, loading (creating the file with defaults on first run), saving, and
a forward-compatible merge so a config written by an older version still loads
when new keys are added.

The config is stored as plain dicts here; the typed ``Profile`` dataclass and
the destination resolver live in ``profiles.py`` and read from this shape.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("gamenote.config")

CONFIG_VERSION = 1


def documents_dir() -> Path:
    """The user's Documents folder, honoring Windows folder redirection (e.g.
    OneDrive or a moved Documents). Falls back to ~/Documents, then ~."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            class _GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            # FOLDERID_Documents: {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            folderid = _GUID(
                0xFDD39AD0,
                0x238F,
                0x46AF,
                (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
            )
            ptr = ctypes.c_wchar_p()
            res = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(folderid), 0, None, ctypes.byref(ptr)
            )
            if res == 0 and ptr.value:
                value = ptr.value
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                return Path(value)
        except Exception as e:  # pragma: no cover - platform/runtime dependent
            log.debug("SHGetKnownFolderPath failed (%s); falling back.", e)

    home = Path.home()
    docs = home / "Documents"
    return docs if docs.exists() else home


def default_dest_root() -> str:
    """Default destination root for new configs: a 'gamenote' folder in the
    user's Documents."""
    return str(documents_dir() / "gamenote")


_DEFAULT_DEST_ROOT = default_dest_root()

# Default profiles shipped on first run. Mirror config.example.json.
#   - Editing notes: per-context file, like the current per-game behavior.
#   - Bugs: a single flat file, no session headers.
#   - Daily log: one file per day.
DEFAULT_CONFIG: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "global": {
        "model_size": "small.en",
        "device": "auto",  # "auto" (GPU then CPU), "cuda" (prefer GPU), or "cpu"
        "beam_size": 1,
        "input_device": None,
        "sample_rate": 16000,
        "frame_ms": 30,
        "silence_threshold": 0.02,
        "silence_seconds": 1.5,
        "start_grace_seconds": 3.0,
        "min_seconds": 0.4,
        "max_seconds": 60.0,
        "language": "en",
        "overlay": {"enabled": True, "hide_ms": 2500},
        "launch_sound": True,
        "launch_sound_file": "",
        "hotkey_beep_file": "",
        "auto_update": True,
        "update_channel": "stable",  # "stable" or "dev"; anything else means stable
        "context": {"value": "", "source": "manual", "file_path": ""},
        "log_level": "INFO",
    },
    "profiles": [
        {
            "id": "editing",
            "name": "Editing notes",
            "hotkey": "alt+f1",
            "dest_root": _DEFAULT_DEST_ROOT,
            "path_template": "{context}_notes.md",
            "line_format": {"timestamp_format": "%Y-%m-%d %H:%M:%S", "prefix": ""},
            "use_session_headers": True,
            "session_from_file": False,
            "session_file": "",
            "clip_from_file": False,
            "clip_file": "",
            "hotkey_beep": True,
            "capture_mode": "vad",
        },
        {
            "id": "bugs",
            "name": "Bugs",
            "hotkey": "alt+f2",
            "dest_root": _DEFAULT_DEST_ROOT,
            "path_template": "bugs.md",
            "line_format": {"timestamp_format": "%Y-%m-%d %H:%M:%S", "prefix": "[bug] "},
            "use_session_headers": False,
            "session_from_file": False,
            "session_file": "",
            "clip_from_file": False,
            "clip_file": "",
            "hotkey_beep": True,
            "capture_mode": "vad",
        },
        {
            "id": "daily",
            "name": "Daily log",
            "hotkey": "alt+f3",
            "dest_root": _DEFAULT_DEST_ROOT,
            "path_template": "{date}_log.md",
            "line_format": {"timestamp_format": "%H:%M:%S", "prefix": ""},
            "use_session_headers": False,
            "session_from_file": False,
            "session_file": "",
            "clip_from_file": False,
            "clip_file": "",
            "hotkey_beep": True,
            "capture_mode": "vad",
        },
    ],
}


def config_dir() -> Path:
    """Per-user config directory: ``%APPDATA%\\gamenote`` on Windows, with a
    home-directory fallback so the module still imports off Windows."""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "gamenote"


def config_path() -> Path:
    return config_dir() / "config.json"


def log_path() -> Path:
    """Log file lives alongside the config so it is writable in a frozen app."""
    return config_dir() / "gamenote.log"


def _merge_defaults(loaded: Any, defaults: Any) -> Any:
    """Recursively fill missing keys in ``loaded`` from ``defaults``. Values
    present in ``loaded`` win. Lists (e.g. ``profiles``) are taken as-is when
    present so user edits are never overwritten."""
    if isinstance(defaults, dict) and isinstance(loaded, dict):
        merged = copy.deepcopy(defaults)
        for key, value in loaded.items():
            if key in merged:
                merged[key] = _merge_defaults(value, merged[key])
            else:
                merged[key] = value
        return merged
    return loaded


def default_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG)


def default_global() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG["global"])


def default_profile_dict(profile_id: str) -> dict[str, Any] | None:
    """The shipped default profile with this id, or None for a custom profile.
    Used by the settings 'restore defaults' button."""
    for p in DEFAULT_CONFIG["profiles"]:
        if p["id"] == profile_id:
            return copy.deepcopy(p)
    return None


def save_config(cfg: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.flush()
        os.fsync(f.fileno())  # durable on disk before the atomic replace
    tmp.replace(path)  # atomic on the same volume
    log.debug("Saved config to %s", path)


def _recover_with_defaults(path: Path, reason: str) -> dict[str, Any]:
    """Back up an unreadable/invalid config to ``config.json.bad`` and write fresh
    defaults, so the user starts clean while their old file is preserved for
    inspection rather than silently overwritten on the next save."""
    log.error("Config at %s is unusable (%s); backing up to .bad and resetting.", path, reason)
    try:
        if path.exists():
            path.replace(path.with_suffix(".json.bad"))
    except OSError as e:
        log.warning("Could not back up the bad config: %s", e)
    cfg = default_config()
    try:
        save_config(cfg)
    except OSError as e:
        log.warning("Could not write fresh defaults: %s", e)
    return cfg


def load_config() -> dict[str, Any]:
    """Load the config, creating it with defaults on first run. Missing keys are
    backfilled from the defaults so older configs keep working."""
    path = config_path()
    if not path.exists():
        cfg = default_config()
        save_config(cfg)
        log.info("Created default config at %s", path)
        return cfg

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return _recover_with_defaults(path, str(e))

    if not isinstance(loaded, dict):
        return _recover_with_defaults(path, "not a JSON object")

    merged = _merge_defaults(loaded, DEFAULT_CONFIG)
    # Type-guard the top-level shape so a hand-edited scalar can't crash later
    # access (e.g. cfg["global"]["context"]).
    if not isinstance(merged.get("global"), dict):
        log.error("Config 'global' is not an object; resetting it to defaults.")
        merged["global"] = default_global()
    if not isinstance(merged.get("profiles"), list):
        log.error("Config 'profiles' is not a list; resetting to defaults.")
        merged["profiles"] = copy.deepcopy(DEFAULT_CONFIG["profiles"])
    return merged
