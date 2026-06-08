"""The settings window: a Global tab and a Profiles tab.

Edits are made against working copies of the profiles and gathered from the
widgets on apply, so Cancel discards cleanly. Applying calls back into the app
(``on_apply``) which persists the config and wires the changes in live:
re-registers hotkeys, updates the overlay, and reloads the model only if the
model size changed and no note is recording.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import Qt, QObject, QEvent
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QLabel,
    QListWidget,
    QPushButton,
    QDialogButtonBox,
    QScrollArea,
    QGroupBox,
    QMessageBox,
    QFrame,
)

from .. import audio as gn_audio
from ..config import default_config, default_global
from ..profiles import Profile, profiles_from_config, validate_profiles
from .profile_editor import ProfileEditor
from .mic_meter import MicMeter

log = logging.getLogger("gamenote.gui.settings")

_MODEL_SIZES = ["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]
_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


class _WheelGuard(QObject):
    """Inside a scroll area, combo and spin boxes eat the mouse wheel and change
    their value instead of letting the page scroll. This redirects the wheel to
    the scroll area when the widget is not focused, so the wheel scrolls the page
    and only a clicked (focused) field reacts to the wheel."""

    def __init__(self, scroll_area: QScrollArea) -> None:
        super().__init__(scroll_area)
        self._sa = scroll_area

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            bar = self._sa.verticalScrollBar()
            bar.setValue(bar.value() - event.angleDelta().y())
            return True
        return False


class SettingsWindow(QDialog):
    def __init__(self, cfg: dict, on_apply: Callable[[list], None], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("gamenote settings")
        self.resize(760, 720)
        self.setMinimumWidth(560)
        self.cfg = cfg
        self.on_apply = on_apply
        self.working_profiles: list[Profile] = [
            Profile.from_dict(p.to_dict()) for p in profiles_from_config(cfg)
        ]

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_global_tab(), "Global")
        self.tabs.addTab(self._build_profiles_tab(), "Profiles")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Apply | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Save).clicked.connect(self._on_save)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._on_apply_clicked)
        buttons.button(QDialogButtonBox.Cancel).clicked.connect(self.close)

        root = QVBoxLayout(self)
        root.addWidget(self.tabs, 1)
        root.addWidget(buttons)

        self._load_global()

    # --- Global tab --------------------------------------------------------

    def _build_global_tab(self) -> QWidget:
        self.context_value = QLineEdit()
        self.context_from_file = QCheckBox("Read context from a file instead")
        self.context_file_path = QLineEdit()
        self.context_from_file.toggled.connect(
            lambda on: self.context_file_path.setEnabled(on)
        )

        self.model_size = QComboBox()
        self.model_size.setEditable(True)
        self.model_size.addItems(_MODEL_SIZES)

        self.beam_size = QSpinBox()
        self.beam_size.setRange(1, 10)

        self.input_device = QComboBox()
        self.input_device.addItem("System default", None)
        for index, name in gn_audio.list_input_devices():
            self.input_device.addItem(f"[{index}] {name}", index)

        self.sample_rate = QSpinBox()
        self.sample_rate.setRange(8000, 48000)
        self.sample_rate.setSingleStep(1000)

        self.frame_ms = QSpinBox()
        self.frame_ms.setRange(10, 60)

        self.silence_threshold = QDoubleSpinBox()
        self.silence_threshold.setRange(0.0, 0.1)
        self.silence_threshold.setDecimals(4)
        self.silence_threshold.setSingleStep(0.0005)

        self.silence_seconds = QDoubleSpinBox()
        self.silence_seconds.setRange(0.1, 30.0)
        self.silence_seconds.setSingleStep(0.1)

        self.start_grace_seconds = QDoubleSpinBox()
        self.start_grace_seconds.setRange(0.5, 30.0)
        self.start_grace_seconds.setSingleStep(0.5)

        self.min_seconds = QDoubleSpinBox()
        self.min_seconds.setRange(0.0, 10.0)
        self.min_seconds.setSingleStep(0.1)

        self.max_seconds = QDoubleSpinBox()
        self.max_seconds.setRange(1.0, 600.0)
        self.max_seconds.setSingleStep(1.0)

        self.overlay_enabled = QCheckBox("Show the confirmation overlay")
        self.overlay_hide_ms = QSpinBox()
        self.overlay_hide_ms.setRange(500, 15000)
        self.overlay_hide_ms.setSingleStep(250)

        self.launch_sound = QCheckBox("Play an arming sound when ready")

        self.auto_update = QCheckBox("Automatically check for updates on launch")

        self.log_level = QComboBox()
        self.log_level.addItems(_LOG_LEVELS)

        self.mic_meter = MicMeter()
        self.silence_threshold.valueChanged.connect(self.mic_meter.set_threshold)
        for w in (self.input_device, self.sample_rate, self.frame_ms):
            w.currentIndexChanged.connect(self._sync_meter) if isinstance(
                w, QComboBox
            ) else w.valueChanged.connect(self._sync_meter)

        context_box = QGroupBox("Context")
        cform = QFormLayout(context_box)
        cform.addRow("Value", self.context_value)
        cform.addRow("", self.context_from_file)
        cform.addRow("File path", self.context_file_path)

        model_box = QGroupBox("Model")
        mform = QFormLayout(model_box)
        mform.addRow("Model size", self.model_size)
        mform.addRow("Beam size", self.beam_size)
        note = QLabel("Changing the model size reloads it (when no note is recording).")
        note.setStyleSheet("color: #888;")
        mform.addRow("", note)

        audio_box = QGroupBox("Audio")
        aform = QFormLayout(audio_box)
        aform.addRow("Input device", self.input_device)
        aform.addRow("Sample rate", self.sample_rate)
        aform.addRow("Frame (ms)", self.frame_ms)

        vad_box = QGroupBox("Silence / timing")
        vform = QFormLayout(vad_box)
        vform.addRow("Silence threshold (RMS)", self.silence_threshold)
        vform.addRow("Mic meter", self.mic_meter)
        vform.addRow("Silence seconds", self.silence_seconds)
        vform.addRow("Start grace seconds", self.start_grace_seconds)
        vform.addRow("Min seconds", self.min_seconds)
        vform.addRow("Max seconds", self.max_seconds)

        overlay_box = QGroupBox("Overlay")
        oform = QFormLayout(overlay_box)
        oform.addRow("", self.overlay_enabled)
        oform.addRow("Hide after (ms)", self.overlay_hide_ms)

        sounds_box = QGroupBox("Sounds")
        sform = QFormLayout(sounds_box)
        sform.addRow("", self.launch_sound)
        snote = QLabel("The per-hotkey beep is set on each profile.")
        snote.setStyleSheet("color: #888;")
        sform.addRow("", snote)

        updates_box = QGroupBox("Updates")
        uform = QFormLayout(updates_box)
        uform.addRow("", self.auto_update)
        unote = QLabel("Checks GitHub Releases. Installing downloads the installer (~500 MB).")
        unote.setStyleSheet("color: #888;")
        uform.addRow("", unote)

        misc_box = QGroupBox("Logging")
        miform = QFormLayout(misc_box)
        miform.addRow("Log level", self.log_level)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        for box in (context_box, model_box, audio_box, vad_box, overlay_box,
                    sounds_box, updates_box, misc_box):
            layout.addWidget(box)
        layout.addStretch(1)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: rgba(255,255,255,0.12);")
        layout.addWidget(sep)
        self.restore_global_btn = QPushButton("Restore global defaults")
        self.restore_global_btn.clicked.connect(self._restore_global_defaults)
        layout.addWidget(self.restore_global_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)

        # Stop combo/spin boxes from hijacking the mouse wheel, and keep a long
        # device name from forcing the field (and window) wider than it should be.
        guard = _WheelGuard(scroll)
        combos = (self.model_size, self.input_device, self.log_level)
        spins = (
            self.beam_size, self.sample_rate, self.frame_ms,
            self.silence_threshold, self.silence_seconds, self.start_grace_seconds,
            self.min_seconds, self.max_seconds, self.overlay_hide_ms,
        )
        for combo in combos:
            combo.setFocusPolicy(Qt.StrongFocus)
            combo.installEventFilter(guard)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
        # The device list can be long; show full names in the popup but elide in the box.
        self.input_device.view().setTextElideMode(Qt.ElideRight)
        for spin in spins:
            spin.setFocusPolicy(Qt.StrongFocus)
            spin.installEventFilter(guard)
        return scroll

    def _load_global(self) -> None:
        self._populate_global(self.cfg["global"])

    def _restore_global_defaults(self) -> None:
        if QMessageBox.question(
            self, "Restore global defaults",
            "Reset all global settings to their defaults?",
        ) != QMessageBox.Yes:
            return
        self._populate_global(default_global())

    def _populate_global(self, g: dict) -> None:
        ctx = g.get("context", {})
        self.context_value.setText(str(ctx.get("value", "")))
        from_file = ctx.get("source", "manual") == "file"
        self.context_from_file.setChecked(from_file)
        self.context_file_path.setText(str(ctx.get("file_path", "")))
        self.context_file_path.setEnabled(from_file)

        self.model_size.setCurrentText(str(g.get("model_size", "small.en")))
        self.beam_size.setValue(int(g.get("beam_size", 1)))

        device = g.get("input_device", None)
        idx = self.input_device.findData(device)
        self.input_device.setCurrentIndex(idx if idx >= 0 else 0)

        self.sample_rate.setValue(int(g.get("sample_rate", 16000)))
        self.frame_ms.setValue(int(g.get("frame_ms", 30)))
        self.silence_threshold.setValue(float(g.get("silence_threshold", 0.006)))
        self.silence_seconds.setValue(float(g.get("silence_seconds", 1.5)))
        self.start_grace_seconds.setValue(float(g.get("start_grace_seconds", 3.0)))
        self.min_seconds.setValue(float(g.get("min_seconds", 0.4)))
        self.max_seconds.setValue(float(g.get("max_seconds", 60.0)))

        overlay = g.get("overlay", {})
        self.overlay_enabled.setChecked(bool(overlay.get("enabled", True)))
        self.overlay_hide_ms.setValue(int(overlay.get("hide_ms", 2500)))
        self.launch_sound.setChecked(bool(g.get("launch_sound", True)))
        self.auto_update.setChecked(bool(g.get("auto_update", True)))
        self.log_level.setCurrentText(str(g.get("log_level", "INFO")))

        self.mic_meter.set_threshold(self.silence_threshold.value())
        self._sync_meter()

    def _sync_meter(self, *_args) -> None:
        self.mic_meter.configure(
            self.input_device.currentData(),
            self.sample_rate.value(),
            self.frame_ms.value(),
        )

    def _gather_global(self) -> dict:
        source = "file" if self.context_from_file.isChecked() else "manual"
        return {
            "model_size": self.model_size.currentText().strip(),
            "beam_size": self.beam_size.value(),
            "input_device": self.input_device.currentData(),
            "sample_rate": self.sample_rate.value(),
            "frame_ms": self.frame_ms.value(),
            "silence_threshold": round(self.silence_threshold.value(), 5),
            "silence_seconds": self.silence_seconds.value(),
            "start_grace_seconds": self.start_grace_seconds.value(),
            "min_seconds": self.min_seconds.value(),
            "max_seconds": self.max_seconds.value(),
            "overlay": {
                "enabled": self.overlay_enabled.isChecked(),
                "hide_ms": self.overlay_hide_ms.value(),
            },
            "launch_sound": self.launch_sound.isChecked(),
            "auto_update": self.auto_update.isChecked(),
            "context": {
                "value": self.context_value.text().strip(),
                "source": source,
                "file_path": self.context_file_path.text().strip(),
            },
            "log_level": self.log_level.currentText(),
        }

    # --- Profiles tab ------------------------------------------------------

    def _build_profiles_tab(self) -> QWidget:
        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._on_profile_selected)

        add = QPushButton("Add")
        add.clicked.connect(self._add_profile)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_profile)
        btn_row = QHBoxLayout()
        btn_row.addWidget(add)
        btn_row.addWidget(remove)
        btn_row.addStretch(1)

        left = QVBoxLayout()
        left.addWidget(self.profile_list, 1)
        left.addLayout(btn_row)
        left_widget = QWidget()
        left_widget.setLayout(left)

        self.editor = ProfileEditor(context_getter=self._preview_context)
        self.editor.changed.connect(self._on_editor_changed)

        layout = QHBoxLayout()
        layout.addWidget(left_widget, 1)
        layout.addWidget(self.editor, 2)
        tab = QWidget()
        tab.setLayout(layout)

        self._reload_profile_list()
        if self.working_profiles:
            self.profile_list.setCurrentRow(0)
        return tab

    def _preview_context(self) -> str:
        # Preview against the value currently typed in the Global tab.
        if self.context_from_file.isChecked():
            return ""
        return self.context_value.text().strip()

    def _reload_profile_list(self) -> None:
        row = self.profile_list.currentRow()
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for p in self.working_profiles:
            self.profile_list.addItem(p.name or p.id or "(unnamed)")
        self.profile_list.blockSignals(False)
        if 0 <= row < len(self.working_profiles):
            self.profile_list.setCurrentRow(row)

    def _on_profile_selected(self, row: int) -> None:
        if 0 <= row < len(self.working_profiles):
            self.editor.set_profile(self.working_profiles[row])
        else:
            self.editor.set_profile(None)

    def _on_editor_changed(self) -> None:
        row = self.profile_list.currentRow()
        if 0 <= row < len(self.working_profiles):
            item = self.profile_list.item(row)
            p = self.working_profiles[row]
            item.setText(p.name or p.id or "(unnamed)")

    def _unique_id(self, base: str = "profile") -> str:
        existing = {p.id for p in self.working_profiles}
        if base not in existing:
            return base
        i = 2
        while f"{base}{i}" in existing:
            i += 1
        return f"{base}{i}"

    def _add_profile(self) -> None:
        new = Profile.from_dict(default_config()["profiles"][0])
        new.id = self._unique_id("profile")
        new.name = "New profile"
        new.hotkey = ""
        self.working_profiles.append(new)
        self._reload_profile_list()
        self.profile_list.setCurrentRow(len(self.working_profiles) - 1)

    def _remove_profile(self) -> None:
        row = self.profile_list.currentRow()
        if not (0 <= row < len(self.working_profiles)):
            return
        name = self.working_profiles[row].name
        if QMessageBox.question(self, "Remove profile", f"Remove '{name}'?") != QMessageBox.Yes:
            return
        del self.working_profiles[row]
        self._reload_profile_list()
        new_row = min(row, len(self.working_profiles) - 1)
        self.profile_list.setCurrentRow(new_row)
        if new_row < 0:
            self.editor.set_profile(None)

    # --- apply / save ------------------------------------------------------

    def _apply(self) -> bool:
        errors = validate_profiles(self.working_profiles)
        if errors:
            QMessageBox.warning(
                self, "Invalid profiles", "Fix these before applying:\n\n- " + "\n- ".join(errors)
            )
            return False
        self.cfg["global"].update(self._gather_global())
        self.cfg["profiles"] = [p.to_dict() for p in self.working_profiles]
        try:
            self.on_apply([Profile.from_dict(p.to_dict()) for p in self.working_profiles])
        except Exception as e:
            log.error("Applying settings failed: %s", e)
            QMessageBox.critical(self, "gamenote", f"Could not apply settings:\n{e}")
            return False
        return True

    def _on_apply_clicked(self) -> None:
        self._apply()

    def _on_save(self) -> None:
        if self._apply():
            self.close()

    def closeEvent(self, event) -> None:
        self.mic_meter.stop()
        super().closeEvent(event)
