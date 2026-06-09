"""Global hotkey registration: map each profile's hotkey to a callback.

The ``keyboard`` library runs its own listener thread and fires callbacks
off-thread. This module only registers and unregisters; it does not touch any
GUI. The registered callback emits a queued Qt signal so the real work runs on
the main thread.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import keyboard

from .profiles import Profile

log = logging.getLogger("gamenote.hotkeys")


class HotkeyManager:
    """Owns the set of registered hotkeys so they can be re-registered as a unit
    (used when profiles change) and paused/resumed (used by the tray)."""

    def __init__(self) -> None:
        self._handles: list[object] = []
        self._mapping: dict[str, Callable[[], None]] = {}
        self.paused = False

    def register(self, mapping: dict[str, Callable[[], None]]) -> list[str]:
        """Register ``{hotkey: callback}``. Replaces any current registration.
        Returns hotkeys that failed to bind (e.g. unknown key name)."""
        self.unregister()
        self._mapping = dict(mapping)
        self.paused = False
        failed: list[str] = []
        if not self._mapping:
            return failed
        for hotkey, callback in self._mapping.items():
            try:
                handle = keyboard.add_hotkey(hotkey, callback)
                self._handles.append(handle)
                log.info("Registered hotkey '%s'", hotkey)
            except Exception as e:
                failed.append(hotkey)
                log.error("Could not register hotkey '%s': %s", hotkey, e)
        return failed

    def set_mapping(self, mapping: dict[str, Callable[[], None]]) -> list[str]:
        """Replace the mapping, applying it now unless paused. When paused the new
        mapping is stored and takes effect on resume(). Returns hotkeys that
        failed to bind (empty when paused)."""
        if self.paused:
            self._mapping = dict(mapping)
            return []
        return self.register(mapping)

    def unregister(self) -> None:
        for handle in self._handles:
            try:
                keyboard.remove_hotkey(handle)
            except (KeyError, ValueError):
                pass
        self._handles.clear()

    def pause(self) -> None:
        """Unbind all hotkeys but remember the mapping for resume()."""
        self.unregister()
        self.paused = True
        log.info("Hotkeys paused")

    def resume(self) -> list[str]:
        """Re-bind the stored mapping. Returns hotkeys that failed to bind (each
        also logged), so a caller can surface them; empty list if not paused."""
        if not self.paused:
            return []
        failed = self.register(self._mapping)
        log.info("Hotkeys resumed")
        return failed


def build_mapping(
    profiles: list[Profile],
    on_profile: Callable[[str], None],
) -> dict[str, Callable[[], None]]:
    """Build ``{hotkey: callback}`` where each callback calls ``on_profile`` with
    that profile's id. Later profiles win on a duplicate hotkey (validation
    surfaces the duplicate separately)."""
    mapping: dict[str, Callable[[], None]] = {}
    for profile in profiles:
        if not profile.hotkey:
            continue
        pid = profile.id

        def make_callback(profile_id: str) -> Callable[[], None]:
            return lambda: on_profile(profile_id)

        mapping[profile.hotkey] = make_callback(pid)
    return mapping
