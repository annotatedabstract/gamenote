import os

import pytest

# Qt must never try to open real windows under pytest (CI has no usable
# desktop session). Set before any Q*Application is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    """Point %APPDATA% at a temp dir so config reads/writes are isolated."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path


@pytest.fixture(scope="session")
def qapp():
    """The process-wide Qt application. A full QApplication (not just
    QCoreApplication) so widget tests work; controller/signal tests only need
    the QCoreApplication part of it. Qt allows exactly one per process, so this
    is session-scoped and shared."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
