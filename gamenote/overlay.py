"""The confirmation overlay, reimplemented in Qt.

A frameless, always-on-top tool window that never steals focus from the game.
Qt's ``WA_ShowWithoutActivating`` plus the ``WindowDoesNotAcceptFocus`` flag
handle most of it; on Windows we also apply the same native ``WS_EX_NOACTIVATE``
ex-style the original Tk overlay used, which is the part that reliably stops
focus theft from a fullscreen game.

All methods run on the main (GUI) thread. The controller drives it by emitting a
queued signal connected to :meth:`Overlay.show_message`.
"""

from __future__ import annotations

import sys
import logging

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

log = logging.getLogger("gamenote.overlay")

_MARGIN = 40  # gap from the top-right screen corner


class Overlay(QWidget):
    def __init__(self, hide_ms: int = 2500) -> None:
        super().__init__()
        self.hide_ms = hide_ms

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(0.92)

        self._label = QLabel("", self)
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self._set_style("#ffffff")
        # Force native window creation so the no-activate style sticks.
        self.winId()
        self._apply_noactivate()

    def _set_style(self, fg: str) -> None:
        self._label.setStyleSheet(
            "QLabel {"
            f" color: {fg};"
            " background-color: #1e1e1e;"
            " font-family: 'Segoe UI';"
            " font-size: 12pt;"
            " padding: 8px 14px;"
            " border-radius: 6px;"
            "}"
        )

    def _apply_noactivate(self) -> None:
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes

            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_TOPMOST = 0x00000008
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            styles = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            styles |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, styles)
        except Exception as e:
            log.debug("Could not apply no-activate window style: %s", e)

    def _reposition(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.adjustSize()
        x = geo.right() - self.width() - _MARGIN
        y = geo.top() + _MARGIN
        self.move(x, y)

    @Slot(str, str, bool)
    def show_message(self, text: str, color: str = "#ffffff", persistent: bool = False) -> None:
        self._set_style(color)
        self._label.setText(text)
        self._reposition()
        self._hide_timer.stop()
        # Show without activating; re-assert the native style each time in case
        # Qt recreated the native window.
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.show()
        self._apply_noactivate()
        if not persistent:
            self._hide_timer.start(self.hide_ms)
