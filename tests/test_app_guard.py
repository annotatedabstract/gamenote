"""Tests for the single-instance guard (named mutex on Windows).

The guard name and fallback port are patched to test-unique values so the
suite neither fails when a real gamenote instance is running on this machine
nor blocks a real launch while the tests hold the guard.
"""

import os
import sys

import pytest

from gamenote import app as gn_app


@pytest.fixture(autouse=True)
def _isolated_guard(monkeypatch):
    monkeypatch.setattr(gn_app, "_MUTEX_NAME", f"Local\\gamenote-test-{os.getpid()}")
    monkeypatch.setattr(gn_app, "SINGLE_INSTANCE_PORT", 49397)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows mutex semantics")
def test_single_instance_guard_blocks_and_releases():
    first = gn_app.single_instance_guard()
    assert first is not None
    try:
        # CreateMutexW on the same name reports ERROR_ALREADY_EXISTS whether the
        # owner is this process or another, so this exercises the real path.
        assert gn_app.single_instance_guard() is None
    finally:
        first.close()
    # Releasing the guard frees the name for the next start.
    third = gn_app.single_instance_guard()
    assert third is not None
    third.close()


def test_guard_close_is_idempotent():
    guard = gn_app.single_instance_guard()
    assert guard is not None
    guard.close()
    guard.close()  # second close must be a no-op, not an error
