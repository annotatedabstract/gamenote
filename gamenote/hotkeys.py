"""Global hotkey registration: map each profile's hotkey to a callback.

The ``keyboard`` library runs its own listener threads and fires callbacks
off-thread. This module registers and unregisters, and watches the library's
threads (ListenerWatchdog) because they can die silently; it does not touch
any GUI. The registered callback emits a queued Qt signal so the real work
runs on the main thread.
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

    def rebind(self) -> list[str]:
        """Re-apply the current mapping, e.g. after the watchdog has recreated
        the keyboard listener. Respects pause (the mapping then binds on
        resume). Returns hotkeys that failed to bind."""
        return self.set_mapping(self._mapping)


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
            def callback() -> None:
                # The keyboard library runs this on its single processing
                # thread with no try/except of its own: an escaping exception
                # kills that thread and silently disables every hotkey for the
                # rest of the process. Never let one escape.
                try:
                    on_profile(profile_id)
                except Exception:
                    log.exception("Hotkey callback for profile '%s' failed", profile_id)

            return callback

        mapping[profile.hotkey] = make_callback(pid)
    return mapping


class ListenerWatchdog:
    """Detects and recovers from the silent death of the keyboard library's
    listener threads.

    The library feeds all hotkeys from one processing thread whose loop has no
    try/except (see the callback wrapper in build_mapping), and its listener
    never restarts a thread once started - so any thread death permanently and
    silently disables every hotkey while the rest of the app looks healthy.
    check(), called periodically from a timer, detects a dead thread, replaces
    the library's module-global listener with a fresh one, and re-binds the
    current mapping. It reaches into keyboard internals (there is no public
    API for any of this), so every access is defensive: with a future keyboard
    version this degrades to a no-op instead of a crash.

    Not covered: Windows silently removing a timed-out low-level keyboard
    hook. Both threads stay alive in that case, so there is nothing to observe
    in-process (see docs/hotkey-hardening.md).
    """

    def __init__(self, manager: HotkeyManager, notify: Callable[[str], None]) -> None:
        self._manager = manager
        self._notify = notify
        self._notified = False  # tell the user once per unrecovered death
        self._disabled = False  # set when keyboard internals look unfamiliar

    def check(self) -> bool:
        """Run one health check, reviving the listener if a thread died.
        Returns True when a recovery was attempted. Never raises."""
        if self._disabled:
            return False
        try:
            dead = self._dead_thread_name()
        except Exception:
            self._disabled = True
            log.exception("Hotkey watchdog cannot inspect the keyboard listener; disabling it.")
            return False
        if dead is None:
            return False
        log.error("keyboard %s died: hotkeys were silently dead. Recreating the listener.", dead)
        try:
            recovered = self._recover()
        except Exception:
            log.exception("Could not recreate the keyboard listener.")
            recovered = False
        if recovered:
            log.info("Keyboard listener recreated and the hotkey mapping re-applied.")
            self._notified = False
        elif not self._notified:
            self._notified = True
            self._notify(
                "Hotkeys stopped working and could not be revived. Please restart gamenote."
            )
        return True

    def _dead_thread_name(self) -> str | None:
        """Name of a keyboard listener thread that has died, or None while
        healthy. Threads that were never started (attribute absent, e.g. no
        hotkey registered yet) count as healthy."""
        listener = getattr(keyboard, "_listener", None)
        for name in ("listening_thread", "processing_thread"):
            thread = getattr(listener, name, None)
            if thread is not None and not thread.is_alive():
                return name
        return None

    def _recover(self) -> bool:
        """Swap in a fresh, unstarted listener and re-bind the current mapping
        (registering starts the new threads and installs a new OS hook).
        Returns False when any hotkey failed to bind."""
        # Unregister against the old listener first so its bookkeeping stays
        # consistent; the handles are dead along with the threads anyway.
        self._manager.unregister()
        # A key-up swallowed around the death (lock screen, UAC) would leave a
        # stale entry that breaks matching for every hotkey; start clean.
        pressed = getattr(keyboard, "_pressed_events", None)
        if pressed is not None:
            lock = getattr(keyboard, "_pressed_events_lock", None)
            if lock is not None:
                with lock:
                    pressed.clear()
            else:
                pressed.clear()
        keyboard._listener = keyboard._KeyboardListener()
        return not self._manager.rebind()
