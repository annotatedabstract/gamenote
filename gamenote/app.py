"""Application bootstrap.

Single-instance guard, QApplication, model load on a background thread, and the
wiring between the hotkey listener, the controller, the overlay, and the tray.
The app launches to the tray with no window open (handoff Section 4).
"""

from __future__ import annotations

import sys
import socket
import logging
import threading
import webbrowser
from pathlib import Path
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMessageBox

from . import config as gn_config
from . import profiles as gn_profiles
from . import hotkeys as gn_hotkeys
from . import transcribe as gn_transcribe
from . import sounds as gn_sounds
from . import updater as gn_updater
from .controller import Controller
from .overlay import Overlay
from .tray import Tray
from .gui.settings_window import SettingsWindow

log = logging.getLogger("gamenote")

SINGLE_INSTANCE_PORT = 49321  # localhost port used only to block a second instance


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


def single_instance_guard() -> socket.socket | None:
    """Bind a localhost port so a second copy refuses to start. Returns the bound
    socket (held for the process lifetime), or None if another instance owns it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        return None
    return s


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

    def load_model_async() -> None:
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
        threading.Thread(target=run, daemon=True).start()

    def on_apply(new_profiles: list) -> None:
        """Apply settings live: persist, swap profiles + hotkeys, update the
        overlay, and reload the model only if its size changed and no note is
        recording."""
        gn_config.save_config(cfg)
        controller.apply_profiles(new_profiles)
        controller.refresh_from_config()
        new_mapping = gn_hotkeys.build_mapping(new_profiles, controller.trigger.emit)
        for hk in manager.set_mapping(new_mapping):
            log.error("Hotkey '%s' failed to register.", hk)
        overlay.hide_ms = int(global_cfg["overlay"]["hide_ms"])
        set_overlay_enabled(bool(global_cfg["overlay"]["enabled"]))
        tray.refresh()
        device_pref = str(global_cfg.get("device", "auto")).lower()
        size_changed = transcriber.loaded_model_size != global_cfg["model_size"]
        device_changed = transcriber.loaded_device_pref != device_pref
        if transcriber.loaded_model_size and (size_changed or device_changed):
            if controller.is_recording:
                QMessageBox.information(
                    None, "gamenote",
                    "The model size or device change will apply next time you open "
                    "settings (a note is recording right now).",
                )
            else:
                log.info("Reloading model (size or device changed).")
                load_model_async()
        log.info("Settings applied.")

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
        updater.check_async(manual)

    def on_update_available(info) -> None:
        pending_update["info"] = info
        tray.set_update_available(info.version)
        tray.show_message(
            "gamenote update available",
            f"Version {info.version} is available. Open the menu to install.",
        )

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
            webbrowser.open(gn_updater.RELEASES_URL)
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
    for hk in manager.register(mapping):
        log.error("Hotkey '%s' failed to register.", hk)
    log.info(
        "Listening for %d hotkey(s): %s",
        len(mapping),
        ", ".join(f"{p.hotkey}->{p.id}" for p in profiles if p.hotkey),
    )

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
