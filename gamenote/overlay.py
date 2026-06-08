"""The confirmation overlay, reimplemented in Qt.

A frameless, always-on-top tool window that never steals focus from the game.
Qt's ``WA_ShowWithoutActivating`` plus the ``WindowDoesNotAcceptFocus`` flag
handle most of it; on Windows we also apply the same native ``WS_EX_NOACTIVATE``
ex-style the original Tk overlay used, which is the part that reliably stops
focus theft from a fullscreen game.

The message can carry a small leading indicator (like the landing-page graphic):
a pulsing cyan dot for "listening", a green check for "saved".

All methods run on the main (GUI) thread. The controller drives it by emitting a
queued signal connected to :meth:`Overlay.show_message`.
"""

from __future__ import annotations

import logging
import math
import sys

from PySide6.QtCore import QAbstractAnimation, Qt, QTimer, QVariantAnimation, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

log = logging.getLogger("gamenote.overlay")

_MARGIN = 40  # gap from the top-right screen corner
_CARD_BG = (30, 30, 30)  # #1e1e1e
_DOT_BRIGHT = (159, 223, 255)  # cyan, matches the landing graphic
_CHECK_GREEN = "#8ef0a0"


class Overlay(QWidget):
    def __init__(self, hide_ms: int = 2500) -> None:
        super().__init__()
        self.hide_ms = hide_ms

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(0.92)

        # The visible rounded box is a "card" containing [indicator][text].
        self._card = QWidget(self)
        self._card.setObjectName("card")

        self._dot = QWidget(self._card)
        self._dot.setFixedSize(10, 10)
        self._dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._check = QLabel("✓", self._card)  # heavy check mark
        self._check.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._check.setStyleSheet(
            f"color: {_CHECK_GREEN}; font-family: 'Segoe UI'; font-weight: 700; font-size: 13pt;"
        )

        self._label = QLabel("", self._card)
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._card_layout = QHBoxLayout(self._card)
        self._card_layout.setContentsMargins(14, 8, 14, 8)
        self._card_layout.setSpacing(9)
        self._card_layout.addWidget(self._dot, 0, Qt.AlignVCenter)
        self._card_layout.addWidget(self._check, 0, Qt.AlignVCenter)
        self._card_layout.addWidget(self._label, 0, Qt.AlignVCenter)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._card)

        # Pulse the dot by interpolating its color toward the card background
        # (solid colors, so no translucent-window / graphics-effect quirks).
        self._pulse = QVariantAnimation(self)
        self._pulse.setStartValue(0.0)
        self._pulse.setEndValue(1.0)
        self._pulse.setDuration(1400)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(self._on_pulse)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self._set_dot_level(1.0)
        self._dot.hide()
        self._check.hide()
        self._set_style("#ffffff")
        # Force native window creation so the no-activate style sticks.
        self.winId()
        self._apply_noactivate()

    def _set_style(self, fg: str, large: bool = False) -> None:
        size = 24 if large else 12  # launch messages ~2x for visibility
        weight = 600 if large else 400
        radius = 10 if large else 6
        vmar, hmar = (12, 22) if large else (8, 14)
        self._card.setStyleSheet(
            f"#card {{ background-color: #1e1e1e; border-radius: {radius}px; }}"
        )
        self._label.setStyleSheet(
            f"color: {fg}; font-family: 'Segoe UI'; font-size: {size}pt; font-weight: {weight};"
        )
        self._card_layout.setContentsMargins(hmar, vmar, hmar, vmar)

    def _set_dot_level(self, k: float) -> None:
        k = max(0.0, min(1.0, k))
        r, g, b = (int(_CARD_BG[i] + k * (_DOT_BRIGHT[i] - _CARD_BG[i])) for i in range(3))
        self._dot.setStyleSheet(f"background-color: rgb({r},{g},{b}); border-radius: 5px;")

    def _on_pulse(self, t) -> None:
        # smooth, symmetric 1.0 -> 0.35 -> 1.0
        k = 0.35 + 0.65 * (0.5 + 0.5 * math.cos(2 * math.pi * float(t)))
        self._set_dot_level(k)

    def _set_indicator(self, indicator: str) -> None:
        if indicator == "dot":
            self._check.hide()
            self._dot.show()
            if self._pulse.state() != QAbstractAnimation.Running:
                self._pulse.start()
        elif indicator == "check":
            self._pulse.stop()
            self._set_dot_level(1.0)
            self._dot.hide()
            self._check.show()
        else:
            self._pulse.stop()
            self._set_dot_level(1.0)
            self._dot.hide()
            self._check.hide()

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

    def _show(
        self, text: str, color: str, persistent: bool, large: bool, indicator: str = "none"
    ) -> None:
        self._set_style(color, large)
        self._label.setText(text)
        self._set_indicator(indicator)
        self._reposition()
        self._hide_timer.stop()
        # Show without activating; re-assert the native style each time in case
        # Qt recreated the native window.
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.show()
        self._apply_noactivate()
        if not persistent:
            self._hide_timer.start(self.hide_ms)

    @Slot(str, str, bool, str)
    def show_message(
        self, text: str, color: str = "#ffffff", persistent: bool = False, indicator: str = "none"
    ) -> None:
        self._show(text, color, persistent, large=False, indicator=indicator)

    @Slot(str, str)
    def show_launch(self, text: str, color: str = "#ffffff") -> None:
        """A larger, more noticeable variant for launch-time confirmations."""
        self._show(text, color, persistent=False, large=True, indicator="none")

    def hide(self) -> None:  # stop the pulse when hidden to save cycles
        self._pulse.stop()
        super().hide()
