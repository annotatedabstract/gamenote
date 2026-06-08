"""Live microphone level meter for silence-threshold calibration.

This replaces the old ``DEBUG = True`` console step: instead of reading ``rms=``
lines from a terminal, the user watches the live RMS here and sets the silence
threshold between the silence floor and their speaking level. A worker thread
reads the mic and emits each frame's RMS; a small painted bar shows the current
level, the recent peak, and a movable threshold marker.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

from PySide6.QtCore import Qt, QObject, Signal, Slot
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QLabel,
)

log = logging.getLogger("gamenote.gui.mic_meter")

_DISPLAY_MAX = 0.06  # RMS at which the bar is full; quiet speech sits well within


class _MeterWorker(QObject):
    rms = Signal(float)
    failed = Signal(str)

    def __init__(self, device, sample_rate: int, frame: int) -> None:
        super().__init__()
        self.device = device
        self.sample_rate = sample_rate
        self.frame = frame
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32",
                                blocksize=self.frame, device=self.device) as stream:
                while not self._stop.is_set():
                    block, _ = stream.read(self.frame)
                    value = float(np.sqrt(np.mean(np.square(block))))
                    self.rms.emit(value)
        except Exception as e:
            log.warning("Mic meter capture failed: %s", e)
            self.failed.emit(str(e))


class _LevelBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(22)
        self.level = 0.0
        self.peak = 0.0
        self.threshold = 0.006

    def set_level(self, value: float) -> None:
        self.level = value
        self.peak = max(self.peak * 0.97, value)  # slow decay so a peak lingers
        self.update()

    def set_threshold(self, value: float) -> None:
        self.threshold = value
        self.update()

    def reset_peak(self) -> None:
        self.peak = 0.0
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#2a2a2a"))

        frac = min(1.0, self.level / _DISPLAY_MAX)
        below = self.level <= self.threshold
        fill_color = QColor("#5aa469") if below else QColor("#2d6cdf")
        p.fillRect(0, 0, int(w * frac), h, fill_color)

        # recent peak marker (thin light line)
        peak_x = int(w * min(1.0, self.peak / _DISPLAY_MAX))
        p.fillRect(max(0, peak_x - 1), 0, 2, h, QColor("#cccccc"))

        # threshold marker (yellow line)
        thr_x = int(w * min(1.0, self.threshold / _DISPLAY_MAX))
        p.fillRect(max(0, thr_x - 1), 0, 2, h, QColor("#ffd24a"))
        p.end()


class MicMeter(QWidget):
    """Start/Stop meter. Provide the device/sample-rate/frame at start time and
    keep the threshold marker in sync via :meth:`set_threshold`."""

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._worker: _MeterWorker | None = None

        self.bar = _LevelBar()
        self.readout = QLabel("RMS: -    peak: -")
        self.button = QPushButton("Start meter")
        self.button.setCheckable(True)
        self.button.toggled.connect(self._on_toggle)

        top = QHBoxLayout()
        top.addWidget(self.bar, 1)
        top.addWidget(self.button)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(top)
        root.addWidget(self.readout)

        self._device = None
        self._sample_rate = 16000
        self._frame = 480

    def configure(self, device, sample_rate: int, frame_ms: int) -> None:
        self._device = device
        self._sample_rate = int(sample_rate)
        self._frame = int(sample_rate * frame_ms / 1000)

    def set_threshold(self, value: float) -> None:
        self.bar.set_threshold(value)

    def _on_toggle(self, checked: bool) -> None:
        if checked:
            self._start()
        else:
            self._stop()

    def _start(self) -> None:
        if self._thread is not None:
            return
        self.bar.reset_peak()
        self._worker = _MeterWorker(self._device, self._sample_rate, self._frame)
        self._worker.rms.connect(self._on_rms, Qt.QueuedConnection)
        self._worker.failed.connect(self._on_failed, Qt.QueuedConnection)
        self._thread = threading.Thread(target=self._worker.run, daemon=True)
        self._thread.start()
        self.button.setText("Stop meter")

    def _stop(self) -> None:
        worker, thread = self._worker, self._thread
        self._worker = None
        self._thread = None
        if worker is not None:
            worker.stop()
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)  # wait for the stream to close (releases the mic)
        self.button.setText("Start meter")
        self.button.setChecked(False)
        self.readout.setText("RMS: -    peak: -")

    @Slot(float)
    def _on_rms(self, value: float) -> None:
        self.bar.set_level(value)
        self.readout.setText(f"RMS: {value:.4f}    peak: {self.bar.peak:.4f}")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._stop()
        self.readout.setText(f"mic error: {message}")

    def stop(self) -> None:
        """Public stop, e.g. when the settings window closes."""
        self._stop()

    def hideEvent(self, event) -> None:
        # Release the mic whenever the meter is hidden -- window closed/minimized,
        # or the user switched tabs -- so it never holds the device in the
        # background or contends with a live recording.
        self._stop()
        super().hideEvent(event)
