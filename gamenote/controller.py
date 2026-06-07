"""Recording state machine and the cross-thread bridge.

The ``keyboard`` listener thread fires a hotkey callback that calls
:meth:`Controller.trigger.emit(profile_id)`. ``trigger`` is connected to
:meth:`Controller.on_profile` with a queued connection, so the slot runs on the
main (GUI) thread (handoff Section 4). ``on_profile`` then spawns a worker thread
for the blocking record + transcribe + file work; the worker reports progress by
emitting ``overlay_message``, which the overlay renders on the main thread.

One global lock guards the single mic: a press while a note is in progress is
ignored with a brief overlay note.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot, Qt

from . import audio as gn_audio
from . import notes as gn_notes
from . import profiles as gn_profiles
from . import sounds as gn_sounds
from .transcribe import Transcriber

log = logging.getLogger("gamenote.controller")

# Overlay colors (kept close to the original daemon's palette).
_C_LISTENING = "#cfe8ff"
_C_SAVED = "#bff7c1"
_C_MUTED = "#cccccc"
_C_WARN = "#ffe9a8"
_C_ERROR = "#ffb3b3"


class Controller(QObject):
    overlay_message = Signal(str, str, bool)  # text, color, persistent
    launch_message = Signal(str, str)         # text, color (large launch-time variant)
    status_changed = Signal(str)              # short status for the tray tooltip
    trigger = Signal(str)                     # profile id, emitted from the hotkey thread

    def __init__(self, transcriber: Transcriber, profiles: list, config: dict) -> None:
        super().__init__()
        self.transcriber = transcriber
        self.profiles = {p.id: p for p in profiles}
        self.config = config
        self._global = config["global"]
        self.debug = str(self._global.get("log_level", "INFO")).upper() == "DEBUG"

        self.lock = threading.Lock()
        self.is_recording = False
        self.stop_event = threading.Event()

        self.trigger.connect(self.on_profile, Qt.QueuedConnection)

    # --- hotkey entry point (runs on the main thread via queued signal) ----

    @Slot(str)
    def on_profile(self, profile_id: str) -> None:
        if profile_id not in self.profiles:
            log.warning("Hotkey fired for unknown profile id '%s'", profile_id)
            return

        if not self.transcriber.ready:
            self.overlay_message.emit("loading...", _C_WARN, False)
            return

        with self.lock:
            if self.is_recording:
                self.overlay_message.emit("busy...", _C_WARN, False)
                return
            self.is_recording = True
            self.stop_event.clear()

        if self.profiles[profile_id].hotkey_beep:
            gn_sounds.play_hotkey_beep()
        self.overlay_message.emit("listening", _C_LISTENING, True)
        threading.Thread(
            target=self._worker, args=(profile_id,), daemon=True
        ).start()

    # --- blocking work (runs on a worker thread) ---------------------------

    def _worker(self, profile_id: str) -> None:
        try:
            profile = self.profiles[profile_id]
            audio = gn_audio.record(self.stop_event, self._global, debug=self.debug)
            if audio is None:
                self.overlay_message.emit("(no note)", _C_MUTED, False)
                return
            text = self.transcriber.transcribe(audio)
            if not text:
                self.overlay_message.emit("(no speech)", _C_MUTED, False)
                return
            context = gn_profiles.read_context(self._global["context"])
            gn_notes.append_note(profile, context, text)
            preview = text if len(text) <= 48 else text[:45] + "..."
            self.overlay_message.emit("saved: " + preview, _C_SAVED, False)
        except gn_audio.AudioCaptureError:
            self.overlay_message.emit("mic error", _C_ERROR, False)
        except Exception as e:
            log.error("Note worker failed: %s", e)
            self.overlay_message.emit("error", _C_ERROR, False)
        finally:
            with self.lock:
                self.is_recording = False

    # --- live settings updates ---------------------------------------------

    def apply_profiles(self, profiles: list) -> None:
        """Swap the active profile set (after a settings edit)."""
        self.profiles = {p.id: p for p in profiles}

    def refresh_from_config(self) -> None:
        """Re-read derived values after the global config was edited in place."""
        self.debug = str(self._global.get("log_level", "INFO")).upper() == "DEBUG"

    # --- context (set from the tray / settings) ----------------------------

    def set_context(self, value: str) -> None:
        """Update the app-owned context in place so the live config reference and
        the next note both see it. Persistence is the caller's job."""
        self._global["context"]["value"] = value
        self._global["context"]["source"] = "manual"
        log.info("Context set to %r", value)

    def current_context(self) -> str:
        return gn_profiles.read_context(self._global["context"])
