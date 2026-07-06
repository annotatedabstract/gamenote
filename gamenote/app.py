"""Application bootstrap.

Single-instance guard, QApplication, model load on a background thread, and the
wiring between the hotkey listener, the controller, the overlay, and the tray.
The app launches to the tray with no window open.
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import config as gn_config
from . import hotkeys as gn_hotkeys
from . import profiles as gn_profiles
from . import sounds as gn_sounds
from . import transcribe as gn_transcribe
from . import updater as gn_updater
from .controller import Controller
from .gui.settings_window import SettingsWindow
from .overlay import Overlay
from .tray import Tray

log = logging.getLogger("gamenote")

SINGLE_INSTANCE_PORT = 49321  # non-Windows fallback: port bind blocks a second copy
_MUTEX_NAME = "Local\\gamenote-single-instance"  # per logon session, like the app


def _setup_logging(global_cfg: dict) -> None:
    # Rotate so the log never grows unbounded: 1 MB x 3 backups.
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            str(gn_config.log_path()), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
    ]
    if sys.stderr is not None:  # pythonw has no console; avoid StreamHandler errors
        handlers.append(logging.StreamHandler())
    level = getattr(logging, str(global_cfg.get("log_level", "INFO")).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )
    for noisy in ("httpx", "httpcore", "huggingface_hub", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class _SingleInstanceGuard:
    """Holds whatever OS object blocks a second instance for the process
    lifetime; ``close()`` releases it (the OS also releases it on exit)."""

    def __init__(self, mutex_handle: int | None = None, sock: socket.socket | None = None) -> None:
        self._handle = mutex_handle
        self._sock = sock

    def close(self) -> None:
        if self._handle is not None:
            try:
                import ctypes

                ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(self._handle))
            except Exception:
                pass
            self._handle = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None


def single_instance_guard() -> _SingleInstanceGuard | None:
    """Block a second copy of the app. On Windows this is a named mutex, which
    cannot false-positive the way the old fixed-port bind could when an
    unrelated program owned the port. Elsewhere (dev convenience) it falls back
    to the port bind. Returns a guard to hold for the process lifetime, or None
    if another gamenote instance already owns it."""
    if sys.platform.startswith("win"):
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p  # never truncate a 64-bit handle
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
            last_error = ctypes.get_last_error()
            ERROR_ACCESS_DENIED = 5
            ERROR_ALREADY_EXISTS = 183
            if handle and last_error == ERROR_ALREADY_EXISTS:
                kernel32.CloseHandle(handle)
                return None
            if handle:
                return _SingleInstanceGuard(mutex_handle=handle)
            if last_error == ERROR_ACCESS_DENIED:
                # An elevated instance owns the mutex and its DACL refuses this
                # unelevated process: that IS "already running", so do not fall
                # through to the port guard (which the other instance never holds).
                return None
            log.warning("CreateMutexW failed (%d); using the port guard.", last_error)
        except Exception as e:  # pragma: no cover - depends on the platform runtime
            log.warning("Mutex guard unavailable (%s); using the port guard.", e)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        return None
    return _SingleInstanceGuard(sock=s)


def _draw_fallback_icon() -> QIcon:
    """A simple drawn icon used when assets/icon.ico is absent."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor("#2d6cdf"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI", 30, QFont.Bold)
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignCenter, "N")
    p.end()
    return QIcon(pix)


def load_icon() -> QIcon:
    candidates = [Path(__file__).with_name("assets") / "icon.ico"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "gamenote" / "assets" / "icon.ico")
    for icon_path in candidates:
        if icon_path.exists():
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                return icon
    return _draw_fallback_icon()


def main() -> int:
    guard = single_instance_guard()
    if guard is None:
        # Need a QApplication so we can show a native message box.
        QApplication.instance() or QApplication(sys.argv)
        QMessageBox.warning(None, "gamenote", "gamenote is already running.")
        return 1

    cfg = gn_config.load_config()
    global_cfg = cfg["global"]
    _setup_logging(global_cfg)
    log.info("Starting gamenote.")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("gamenote")
    app.setQuitOnLastWindowClosed(False)  # live in the tray, not a window

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "gamenote", "No system tray is available.")
        return 1

    icon = load_icon()
    app.setWindowIcon(icon)

    profiles = gn_profiles.profiles_from_config(cfg)
    for problem in gn_profiles.validate_profiles(profiles):
        log.warning("Profile config: %s", problem)

    transcriber = gn_transcribe.Transcriber(global_cfg)
    controller = Controller(transcriber, profiles, cfg)

    overlay = Overlay(hide_ms=int(global_cfg["overlay"]["hide_ms"]))
    overlay_state = {"connected": False}

    def set_overlay_enabled(enabled: bool) -> None:
        if enabled and not overlay_state["connected"]:
            controller.overlay_message.connect(overlay.show_message, Qt.QueuedConnection)
            controller.launch_message.connect(overlay.show_launch, Qt.QueuedConnection)
            overlay_state["connected"] = True
        elif not enabled and overlay_state["connected"]:
            for signal, slot in (
                (controller.overlay_message, overlay.show_message),
                (controller.launch_message, overlay.show_launch),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            overlay_state["connected"] = False

    set_overlay_enabled(bool(global_cfg["overlay"]["enabled"]))

    manager = gn_hotkeys.HotkeyManager()
    windows: dict[str, SettingsWindow] = {}

    class _LoadSignals(QObject):
        finished = Signal()  # a model load attempt ended (success or failure)

    load_signals = _LoadSignals()
    model_loading = {"active": False}  # guards against overlapping load threads

    def load_model_async() -> None:
        if model_loading["active"]:
            return
        model_loading["active"] = True

        def run() -> None:
            try:
                if not gn_transcribe.model_available(global_cfg["model_size"]):
                    controller.status_changed.emit("downloading model")
                    controller.launch_message.emit(
                        "downloading model (one time, ~480 MB)...", "#ffe9a8"
                    )
                else:
                    controller.status_changed.emit("loading")
                device = transcriber.load()
                controller.status_changed.emit(f"ready ({device})")
                if str(global_cfg.get("device", "auto")).lower() == "cuda" and device != "cuda":
                    controller.launch_message.emit(
                        "GPU unavailable - running on CPU (check the CUDA libraries)",
                        "#ffe9a8",
                    )
                else:
                    controller.launch_message.emit("gamenote ready", "#cfe8ff")
                if bool(global_cfg.get("launch_sound", True)):
                    gn_sounds.play_arming(global_cfg.get("launch_sound_file") or None)
            except Exception as e:
                log.error("Model load failed: %s", e)
                controller.status_changed.emit("model error")
                controller.launch_message.emit("model load failed", "#ffb3b3")
            finally:
                # Clear the guard before the queued signal fires, so the
                # follow-up reload check sees an idle loader.
                model_loading["active"] = False
                load_signals.finished.emit()

        threading.Thread(target=run, daemon=True).start()

    def check_model_reload() -> None:
        """Start a model reload when a settings change to the model size or
        device is waiting (see Transcriber.needs_reload). Runs after every
        settings apply, after every note, and after every load, so a change
        made mid-recording or mid-load is applied as soon as it safely can
        be."""
        if model_loading["active"] or controller.is_recording:
            return
        if transcriber.needs_reload():
            log.info("Model size or device changed; reloading.")
            load_model_async()

    load_signals.finished.connect(check_model_reload, Qt.QueuedConnection)
    controller.note_finished.connect(check_model_reload, Qt.QueuedConnection)

    def on_apply(new_profiles: list) -> list[str]:
        """Apply settings live: persist, swap profiles + hotkeys, update the
        overlay, and reload the model if its size or device changed (deferred
        automatically while a note is recording or a load is running). Returns
        the hotkeys that failed to register so the caller can surface them."""
        gn_config.save_config(cfg)
        controller.apply_profiles(new_profiles)
        controller.refresh_from_config()
        new_mapping = gn_hotkeys.build_mapping(new_profiles, controller.trigger.emit)
        failed = manager.set_mapping(new_mapping)
        for hk in failed:
            log.error("Hotkey '%s' failed to register.", hk)
        overlay.hide_ms = int(global_cfg["overlay"]["hide_ms"])
        set_overlay_enabled(bool(global_cfg["overlay"]["enabled"]))
        tray.refresh()
        if transcriber.needs_reload() and (controller.is_recording or model_loading["active"]):
            QMessageBox.information(
                None,
                "gamenote",
                "The model size or device change will be applied automatically "
                "as soon as the current note or model load finishes.",
            )
        check_model_reload()
        log.info("Settings applied.")
        return failed

    def open_settings() -> None:
        existing = windows.get("settings")
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        win = SettingsWindow(cfg, on_apply)
        windows["settings"] = win

        def _forget(_obj=None, _win=win):
            # On close the dialog deletes itself (WA_DeleteOnClose); drop our
            # reference, but only if it is still the current one.
            if windows.get("settings") is _win:
                windows.pop("settings", None)

        win.destroyed.connect(_forget)
        win.show()
        win.raise_()
        win.activateWindow()

    def quit_app() -> None:
        log.info("Quitting.")
        manager.unregister()
        app.quit()

    # --- updates ----------------------------------------------------------
    updater = gn_updater.Updater()
    pending_update: dict = {"info": None}

    def do_check(manual: bool = False) -> None:
        # Read the channel at call time: settings Apply mutates global_cfg in
        # place, so a channel change applies to the very next check.
        channel = str(global_cfg.get("update_channel", "stable")).lower()
        updater.check_async(manual, channel=channel)

    def on_update_available(info) -> None:
        pending_update["info"] = info
        tray.set_update_available(info.version)
        if getattr(info, "channel", "stable") == "dev":
            body = f"Build {info.version} is available. Open the menu to install."
        else:
            body = f"Version {info.version} is available. Open the menu to install."
        tray.show_message("gamenote update available", body)

    def on_up_to_date(manual: bool) -> None:
        if manual:
            tray.show_message("gamenote", "You are on the latest version.")

    def on_update_failed(manual: bool, message: str) -> None:
        log.info("Update flow problem: %s", message)
        if manual:
            tray.show_message("gamenote", "Could not check for updates.")

    def on_progress(done: int, total: int) -> None:
        pct = int(done * 100 / total) if total else 0
        tray.tray.setToolTip(f"gamenote - downloading update {pct}%")

    def on_ready(path: str) -> None:
        tray.show_message("gamenote", "Update downloaded. Installing now...")
        gn_updater.run_installer(path)
        quit_app()

    def on_install_update() -> None:
        info = pending_update.get("info")
        if info is None:
            return
        if not gn_updater.is_frozen():
            dev = getattr(info, "channel", "stable") == "dev"
            webbrowser.open(gn_updater.DEV_RELEASES_URL if dev else gn_updater.RELEASES_URL)
            return
        tray.show_message("gamenote", f"Downloading update {info.version} (~90 MB)...")
        updater.download_async(info)

    tray = Tray(
        icon=icon,
        controller=controller,
        hotkey_manager=manager,
        on_open_settings=open_settings,
        on_quit=quit_app,
        save_config=lambda: gn_config.save_config(cfg),
        on_check_updates=lambda: do_check(manual=True),
        on_install_update=on_install_update,
    )

    updater.available.connect(on_update_available, Qt.QueuedConnection)
    updater.up_to_date.connect(on_up_to_date, Qt.QueuedConnection)
    updater.failed.connect(on_update_failed, Qt.QueuedConnection)
    updater.progress.connect(on_progress, Qt.QueuedConnection)
    updater.ready.connect(on_ready, Qt.QueuedConnection)

    # Register hotkeys now; presses are ignored with a "loading" overlay until
    # the model is ready.
    mapping = gn_hotkeys.build_mapping(profiles, controller.trigger.emit)
    startup_failed = manager.register(mapping)
    for hk in startup_failed:
        log.error("Hotkey '%s' failed to register.", hk)
    if startup_failed:
        # Balloon after the event loop is up, so the user learns about it
        # without having to read the log.
        QTimer.singleShot(
            1500,
            lambda: tray.show_message(
                "gamenote",
                "Could not register hotkey(s): "
                + ", ".join(startup_failed)
                + ". Check Settings > Profiles.",
            ),
        )
    log.info(
        "Listening for %d hotkey(s): %s",
        len(mapping),
        ", ".join(f"{p.hotkey}->{p.id}" for p in profiles if p.hotkey),
    )

    # The keyboard library's listener threads can die silently and it never
    # restarts them; watch and revive so hotkeys don't stay dead until the
    # next app restart (see ListenerWatchdog).
    watchdog = gn_hotkeys.ListenerWatchdog(
        manager, notify=lambda text: tray.show_message("gamenote", text)
    )
    watchdog_timer = QTimer()
    watchdog_timer.setInterval(60_000)
    watchdog_timer.timeout.connect(watchdog.check)
    watchdog_timer.start()

    if gn_transcribe.nvidia_dll_dirs():
        log.info("Added NVIDIA DLL dirs for GPU: %s", ", ".join(gn_transcribe.nvidia_dll_dirs()))
    else:
        log.info("No NVIDIA DLL dirs added; using CPU unless cuBLAS/cuDNN are on PATH.")

    load_model_async()

    if gn_updater.is_frozen() and bool(global_cfg.get("auto_update", True)):
        do_check(manual=False)

    exit_code = app.exec()
    manager.unregister()
    if guard is not None:
        guard.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
