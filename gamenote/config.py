"""Configuration storage for gamenote.

The single source of truth for runtime settings is a JSON file at
``%APPDATA%\\gamenote\\config.json``. This module owns the schema, the
defaults, loading (creating the file with defaults on first run), saving, and
a forward-compatible merge so a config written by an older version still loads
when new keys are added.

Stage 1 keeps this dict-based. The typed ``Profile`` dataclass and the
destination resolver arrive in Stage 2 (``profiles.py``); the shape stored here
already matches Section 5 of the handoff so that later stages only add code,
not migrations.
"""

from __future__ import annotations

import os
import sys
import copy
import json
import logging
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
                0xFDD39AD0, 0x238F, 0x46AF,
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
        "beam_size": 1,
        "input_device": None,
        "sample_rate": 16000,
        "frame_ms": 30,
        "silence_threshold": 0.02,
        "silence_seconds": 1.5,
        "start_grace_seconds": 3.0,
        "min_seconds": 0.4,
        "max_seconds": 60.0,
        "overlay": {"enabled": True, "hide_ms": 2500},
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
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic on the same volume
    log.debug("Saved config to %s", path)


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
        log.error("Could not read config at %s (%s). Using defaults.", path, e)
        return default_config()

    if not isinstance(loaded, dict):
        log.error("Config at %s is not a JSON object. Using defaults.", path)
        return default_config()

    return _merge_defaults(loaded, DEFAULT_CONFIG)
