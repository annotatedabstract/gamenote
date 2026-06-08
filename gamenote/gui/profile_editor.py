"""Editor for a single profile: name, hotkey (with capture), destination root,
path template (with a live preview of the resolved path), line format, and the
session-header toggle. Edits are written back to the bound Profile live; the
``changed`` signal lets the parent refresh the list and re-validate.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import config as gn_config
from ..profiles import Profile


def qkeyseq_to_hotkey(seq: QKeySequence) -> str:
    """Convert a Qt key sequence to the ``keyboard`` library's format
    (lowercase, '+'-joined), e.g. 'Ctrl+Alt+N' -> 'ctrl+alt+n', 'F13' -> 'f13'.
    Only the first chord is used."""
    text = seq.toString(QKeySequence.PortableText)
    if not text:
        return ""
    first = text.split(",")[0].strip()
    return first.lower().replace("meta", "windows")


class _CaptureDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Capture hotkey")
        self.edit = QKeySequenceEdit()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Press the key or combo (e.g. F13, or Ctrl+Alt+N):"))
        layout.addWidget(self.edit)
        layout.addWidget(buttons)

    def hotkey(self) -> str:
        return qkeyseq_to_hotkey(self.edit.keySequence())


class ProfileEditor(QWidget):
    changed = Signal()

    def __init__(self, context_getter=None) -> None:
        super().__init__()
        self._profile: Profile | None = None
        self._loading = False
        self._context_getter = context_getter or (lambda: "")

        self.name = QLineEdit()
        self.hotkey = QLineEdit()
        capture = QPushButton("Capture...")
        capture.clicked.connect(self._capture_hotkey)
        hk_row = QHBoxLayout()
        hk_row.setContentsMargins(0, 0, 0, 0)
        hk_row.addWidget(self.hotkey, 1)
        hk_row.addWidget(capture)
        hk_widget = QWidget()
        hk_widget.setLayout(hk_row)

        self.dest_root = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_root)
        dr_row = QHBoxLayout()
        dr_row.setContentsMargins(0, 0, 0, 0)
        dr_row.addWidget(self.dest_root, 1)
        dr_row.addWidget(browse)
        dr_widget = QWidget()
        dr_widget.setLayout(dr_row)

        self.capture_mode = QComboBox()
        self.capture_mode.addItem("Auto-stop on silence (VAD)", "vad")
        self.capture_mode.addItem("Push-to-talk (press again to stop)", "toggle")

        self.path_template = QLineEdit()
        self.timestamp_format = QLineEdit()
        self.prefix = QLineEdit()
        self.use_session_headers = QCheckBox("Write session headers")

        # Legacy: source the session header value from a .current_session file.
        self.session_from_file = QCheckBox("Read session value from a file (legacy OBS .current_session)")
        self.session_file = QLineEdit()
        sf_browse = QPushButton("Browse...")
        sf_browse.clicked.connect(self._browse_session_file)
        sf_row = QHBoxLayout()
        sf_row.setContentsMargins(0, 0, 0, 0)
        sf_row.addWidget(self.session_file, 1)
        sf_row.addWidget(sf_browse)
        self.session_file_widget = QWidget()
        self.session_file_widget.setLayout(sf_row)
        self.session_hint = QLabel("Empty or missing file falls back to the date.")
        self.session_hint.setStyleSheet("color: #888;")

        # Stamp the note's position into the current OBS recording, read from a
        # gamenote-obs.json sidecar. The value fills the {clip} token in the prefix.
        self.clip_from_file = QCheckBox("Stamp recording position from an OBS file")
        self.clip_file = QLineEdit()
        cf_browse = QPushButton("Browse...")
        cf_browse.clicked.connect(self._browse_clip_file)
        cf_row = QHBoxLayout()
        cf_row.setContentsMargins(0, 0, 0, 0)
        cf_row.addWidget(self.clip_file, 1)
        cf_row.addWidget(cf_browse)
        self.clip_file_widget = QWidget()
        self.clip_file_widget.setLayout(cf_row)
        self.clip_hint = QLabel('Reads gamenote-obs.json (see integrations/obs). Put '
                                '{clip} in the line prefix, e.g. "[{clip}] ". Omitted '
                                'when no recording is active.')
        self.clip_hint.setWordWrap(True)
        self.clip_hint.setStyleSheet("color: #888;")

        self.hotkey_beep = QCheckBox("Beep when this profile's hotkey fires")

        self.preview = QLabel("-")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview.setStyleSheet("color: #888;")

        form = QFormLayout(self)
        form.addRow("Name", self.name)
        form.addRow("Hotkey", hk_widget)
        form.addRow("Capture mode", self.capture_mode)
        form.addRow("Destination root", dr_widget)
        form.addRow("Path template", self.path_template)
        form.addRow("Timestamp format", self.timestamp_format)
        form.addRow("Line prefix", self.prefix)
        form.addRow("", self.use_session_headers)
        form.addRow("", self.session_from_file)
        form.addRow("Session file", self.session_file_widget)
        form.addRow("", self.session_hint)
        form.addRow("", self.clip_from_file)
        form.addRow("Recording file", self.clip_file_widget)
        form.addRow("", self.clip_hint)
        form.addRow("", self.hotkey_beep)
        form.addRow("Resolved path", self.preview)
        tokens = QLabel("Tokens: {profile} {context} {date} {time}")
        tokens.setStyleSheet("color: #888;")
        form.addRow("", tokens)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: rgba(255,255,255,0.12);")
        form.addRow(sep)
        self.restore_btn = QPushButton("Restore profile defaults")
        self.restore_btn.clicked.connect(self._restore_defaults)
        form.addRow(self.restore_btn)

        self.name.textChanged.connect(self._on_edit)
        self.hotkey.textChanged.connect(self._on_edit)
        self.capture_mode.currentIndexChanged.connect(self._on_edit)
        self.dest_root.textChanged.connect(self._on_edit)
        self.path_template.textChanged.connect(self._on_edit)
        self.timestamp_format.textChanged.connect(self._on_edit)
        self.prefix.textChanged.connect(self._on_edit)
        self.use_session_headers.toggled.connect(self._on_edit)
        self.session_from_file.toggled.connect(self._on_edit)
        self.session_file.textChanged.connect(self._on_edit)
        self.clip_from_file.toggled.connect(self._on_edit)
        self.clip_file.textChanged.connect(self._on_edit)
        self.hotkey_beep.toggled.connect(self._on_edit)
        self.use_session_headers.toggled.connect(self._sync_session_enable)
        self.session_from_file.toggled.connect(self._sync_session_enable)
        self.clip_from_file.toggled.connect(self._sync_clip_enable)

        self.setEnabled(False)

    def set_profile(self, profile: Profile | None) -> None:
        self._profile = profile
        self.setEnabled(profile is not None)
        self._loading = True
        if profile is not None:
            self.name.setText(profile.name)
            self.hotkey.setText(profile.hotkey)
            mode_idx = self.capture_mode.findData(profile.capture_mode)
            self.capture_mode.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)
            self.dest_root.setText(profile.dest_root)
            self.path_template.setText(profile.path_template)
            self.timestamp_format.setText(profile.line_format.timestamp_format)
            self.prefix.setText(profile.line_format.prefix)
            self.use_session_headers.setChecked(profile.use_session_headers)
            self.session_from_file.setChecked(profile.session_from_file)
            self.session_file.setText(profile.session_file)
            self.clip_from_file.setChecked(profile.clip_from_file)
            self.clip_file.setText(profile.clip_file)
            self.hotkey_beep.setChecked(profile.hotkey_beep)
        else:
            for w in (self.name, self.hotkey, self.dest_root, self.path_template,
                      self.timestamp_format, self.prefix, self.session_file,
                      self.clip_file):
                w.clear()
        self._loading = False
        self._sync_session_enable()
        self._sync_clip_enable()
        self._update_preview()

    def _on_edit(self, *_args) -> None:
        if self._loading or self._profile is None:
            return
        p = self._profile
        p.name = self.name.text()
        p.hotkey = self.hotkey.text().strip().lower()
        p.capture_mode = self.capture_mode.currentData()
        p.dest_root = self.dest_root.text()
        p.path_template = self.path_template.text()
        p.line_format.timestamp_format = self.timestamp_format.text()
        p.line_format.prefix = self.prefix.text()
        p.use_session_headers = self.use_session_headers.isChecked()
        p.session_from_file = self.session_from_file.isChecked()
        p.session_file = self.session_file.text().strip()
        p.clip_from_file = self.clip_from_file.isChecked()
        p.clip_file = self.clip_file.text().strip()
        p.hotkey_beep = self.hotkey_beep.isChecked()
        self._update_preview()
        self.changed.emit()

    def _sync_session_enable(self, *_args) -> None:
        headers = self.use_session_headers.isChecked()
        self.session_from_file.setEnabled(headers)
        from_file = headers and self.session_from_file.isChecked()
        self.session_file_widget.setEnabled(from_file)
        self.session_hint.setEnabled(from_file)

    def _sync_clip_enable(self, *_args) -> None:
        on = self.clip_from_file.isChecked()
        self.clip_file_widget.setEnabled(on)
        self.clip_hint.setEnabled(on)

    def _update_preview(self) -> None:
        if self._profile is None:
            self.preview.setText("-")
            return
        try:
            context = self._context_getter()
            path = self._profile.resolve_path(context, datetime.now())
            self.preview.setText(str(path))
        except Exception as e:
            self.preview.setText(f"(invalid template: {e})")

    def _capture_hotkey(self) -> None:
        dialog = _CaptureDialog(self)
        if dialog.exec() == QDialog.Accepted:
            hk = dialog.hotkey()
            if hk:
                self.hotkey.setText(hk)

    def _browse_root(self) -> None:
        start = self.dest_root.text() or ""
        chosen = QFileDialog.getExistingDirectory(self, "Choose destination root", start)
        if chosen:
            self.dest_root.setText(chosen)

    def _browse_session_file(self) -> None:
        start = self.session_file.text() or ""
        chosen, _ = QFileDialog.getOpenFileName(self, "Choose .current_session file", start)
        if chosen:
            self.session_file.setText(chosen)

    def _browse_clip_file(self) -> None:
        start = self.clip_file.text() or ""
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choose gamenote-obs.json file", start, "JSON (*.json);;All files (*)"
        )
        if chosen:
            self.clip_file.setText(chosen)

    def _restore_defaults(self) -> None:
        if self._profile is None:
            return
        label = self._profile.name or self._profile.id
        if QMessageBox.question(
            self, "Restore profile defaults",
            f"Reset '{label}' to its default settings?",
        ) != QMessageBox.Yes:
            return

        defaults = gn_config.default_profile_dict(self._profile.id)
        if defaults is not None:
            src = Profile.from_dict(defaults)           # shipped profile: full reset
            reset_identity = True
        else:
            src = Profile.from_dict(gn_config.default_config()["profiles"][0])
            reset_identity = False                      # custom: keep name/hotkey

        p = self._profile
        if reset_identity:
            p.name = src.name
            p.hotkey = src.hotkey
        p.capture_mode = src.capture_mode
        p.dest_root = src.dest_root
        p.path_template = src.path_template
        p.line_format = src.line_format
        p.use_session_headers = src.use_session_headers
        p.session_from_file = src.session_from_file
        p.session_file = src.session_file
        p.clip_from_file = src.clip_from_file
        p.clip_file = src.clip_file
        p.hotkey_beep = src.hotkey_beep
        # p.id is the profile's identity and is left unchanged.
        self.set_profile(p)
        self.changed.emit()
