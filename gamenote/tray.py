"""System tray presence: a QSystemTrayIcon with a menu to set the context,
pause/resume hotkeys, open settings, and quit.

The app lives here, not in an always-open window. The tray tooltip reflects
whether the model is still loading, ready, or hotkeys are paused.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Slot
from PySide6.QtGui import QIcon, QAction, QCursor
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QInputDialog

from .controller import Controller
from .hotkeys import HotkeyManager

log = logging.getLogger("gamenote.tray")

_MAX_RECENT = 6


class Tray(QObject):
    def __init__(
        self,
        icon: QIcon,
        controller: Controller,
        hotkey_manager: HotkeyManager,
        on_open_settings: Callable[[], None],
        on_quit: Callable[[], None],
        save_config: Callable[[], None],
        on_check_updates: Callable[[], None] | None = None,
        on_install_update: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.hotkeys = hotkey_manager
        self.on_open_settings = on_open_settings
        self.on_quit = on_quit
        self.save_config = save_config
        self.on_check_updates = on_check_updates
        self.on_install_update = on_install_update
        self.update_version: str | None = None

        self.status = "loading"
        self.recent: list[str] = []
        current = controller.current_context()
        if current:
            self.recent.append(current)

        self.tray = QSystemTrayIcon(icon, self)
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self._build_menu()
        self._refresh_tooltip()
        self.tray.show()

        controller.status_changed.connect(self.set_status)
        self.tray.activated.connect(self._on_activated)

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left-click (Trigger) and double-click also open the menu; right-click
        # uses Qt's built-in context menu.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.menu.popup(QCursor.pos())

    # --- menu --------------------------------------------------------------

    def _build_menu(self) -> None:
        self.menu.clear()

        header = QAction(f"gamenote - {self.status}", self.menu)
        header.setEnabled(False)
        self.menu.addAction(header)
        self.menu.addSeparator()

        if self.update_version and self.on_install_update is not None:
            update = QAction(f"Install update ({self.update_version})", self.menu)
            update.triggered.connect(lambda: self.on_install_update())
            self.menu.addAction(update)
            self.menu.addSeparator()

        context_menu = self.menu.addMenu("Set context")
        current = self.controller.current_context()
        for ctx in self.recent:
            act = QAction(ctx or "(empty)", context_menu)
            act.setCheckable(True)
            act.setChecked(ctx == current)
            act.triggered.connect(lambda _checked=False, c=ctx: self._choose_context(c))
            context_menu.addAction(act)
        if self.recent:
            context_menu.addSeparator()
        set_new = QAction("Set new context...", context_menu)
        set_new.triggered.connect(self._prompt_context)
        context_menu.addAction(set_new)
        clear = QAction("Clear context", context_menu)
        clear.triggered.connect(lambda: self._choose_context(""))
        context_menu.addAction(clear)

        self.pause_action = QAction("Pause hotkeys", self.menu)
        self.pause_action.setCheckable(True)
        self.pause_action.setChecked(self.hotkeys.paused)
        self.pause_action.toggled.connect(self._toggle_pause)
        self.menu.addAction(self.pause_action)

        settings = QAction("Settings...", self.menu)
        settings.triggered.connect(lambda: self.on_open_settings())
        self.menu.addAction(settings)

        if self.on_check_updates is not None:
            check = QAction("Check for updates...", self.menu)
            check.triggered.connect(lambda: self.on_check_updates())
            self.menu.addAction(check)

        self.menu.addSeparator()
        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(lambda: self.on_quit())
        self.menu.addAction(quit_action)

    def _refresh_tooltip(self) -> None:
        current = self.controller.current_context()
        status = "hotkeys paused" if self.hotkeys.paused else self.status
        self.tray.setToolTip(f"gamenote - {status}\nContext: {current or '(none)'}")

    # --- actions -----------------------------------------------------------

    def _prompt_context(self) -> None:
        current = self.controller.current_context()
        value, ok = QInputDialog.getText(
            None, "Set context", "Context (e.g. the game name):", text=current
        )
        if ok:
            self._choose_context(value.strip())

    def _choose_context(self, value: str) -> None:
        self.controller.set_context(value)
        if value and value in self.recent:
            self.recent.remove(value)
        if value:
            self.recent.insert(0, value)
            del self.recent[_MAX_RECENT:]
        self.save_config()
        self._build_menu()
        self._refresh_tooltip()

    def _toggle_pause(self, checked: bool) -> None:
        if checked:
            self.hotkeys.pause()
        else:
            self.hotkeys.resume()
        self._refresh_tooltip()

    @Slot(str)
    def set_status(self, status: str) -> None:
        self.status = status
        self._build_menu()
        self._refresh_tooltip()

    def refresh(self) -> None:
        """Rebuild the menu and tooltip, e.g. after settings were applied."""
        self._build_menu()
        self._refresh_tooltip()

    def set_update_available(self, version: str | None) -> None:
        """Show or clear the 'Install update' menu entry."""
        self.update_version = version
        self._build_menu()

    def show_message(self, title: str, message: str) -> None:
        self.tray.showMessage(title, message, self.tray.icon())
