import pytest


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    """Point %APPDATA% at a temp dir so config reads/writes are isolated."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path
