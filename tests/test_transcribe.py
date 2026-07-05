import sys
import types

import pytest

from gamenote import transcribe as gn_transcribe
from gamenote.transcribe import Transcriber, _device_attempts, resolve_model_source


def _install_fake_faster_whisper(monkeypatch, fail_devices=()):
    """Put a stub `faster_whisper` module in sys.modules so Transcriber.load()'s
    lazy import picks up a fake WhisperModel (no heavy backend needed). Returns
    the list of (device, compute_type) pairs the loader attempted."""
    attempts = []

    class _FakeWhisperModel:
        def __init__(self, source, device="cpu", compute_type="int8", **kw):
            attempts.append((device, compute_type))
            if device in fail_devices:
                raise RuntimeError(f"{device} unavailable")

        def transcribe(self, *a, **k):
            return ([], None)  # _warmup does list(model.transcribe(...)[0])

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    return attempts


def test_auto_prefers_gpu_then_cpu():
    assert _device_attempts("auto") == [("cuda", "float16"), ("cpu", "int8")]


def test_cuda_also_falls_back_to_cpu():
    # "Force GPU" still falls back so a missing CUDA install doesn't brick the
    # app; the caller warns the user when the GPU did not engage.
    assert _device_attempts("cuda") == [("cuda", "float16"), ("cpu", "int8")]


def test_cpu_is_the_only_attempt():
    assert _device_attempts("cpu") == [("cpu", "int8")]


def test_blank_and_unknown_default_to_auto():
    assert _device_attempts("") == [("cuda", "float16"), ("cpu", "int8")]
    assert _device_attempts("something-else") == [("cuda", "float16"), ("cpu", "int8")]


def test_value_is_normalized():
    assert _device_attempts("  CPU  ") == [("cpu", "int8")]


def test_load_falls_back_from_cuda_to_cpu(monkeypatch):
    attempts = _install_fake_faster_whisper(monkeypatch, fail_devices=("cuda",))
    t = Transcriber({"model_size": "small.en", "device": "auto", "sample_rate": 16000})
    assert t.load() == "cpu"
    assert t.device == "cpu"
    assert t.loaded_device_pref == "auto"
    assert [d for d, _ in attempts] == ["cuda", "cpu"]


def test_load_force_cpu_never_tries_cuda(monkeypatch):
    attempts = _install_fake_faster_whisper(monkeypatch, fail_devices=())
    t = Transcriber({"model_size": "small.en", "device": "cpu", "sample_rate": 16000})
    assert t.load() == "cpu"
    assert [d for d, _ in attempts] == ["cpu"]


def test_load_records_attempted_target_even_on_failure(monkeypatch):
    # The app's deferred-reload check compares the config against the last
    # *attempted* target, so a failing load must still record what it tried
    # (otherwise the app would retry the same failing target in a loop).
    _install_fake_faster_whisper(monkeypatch, fail_devices=("cpu",))
    t = Transcriber({"model_size": "small.en", "device": "cpu", "sample_rate": 16000})
    with pytest.raises(RuntimeError):
        t.load()
    assert t.attempted_model_size == "small.en"
    assert t.attempted_device_pref == "cpu"
    assert t.loaded_model_size == ""  # nothing actually loaded
    assert t.load_failed is True


def test_load_records_attempted_target_on_success(monkeypatch):
    _install_fake_faster_whisper(monkeypatch)
    t = Transcriber({"model_size": "small.en", "device": "cpu", "sample_rate": 16000})
    t.load()
    assert t.attempted_model_size == t.loaded_model_size == "small.en"
    assert t.attempted_device_pref == t.loaded_device_pref == "cpu"


def test_needs_reload_tracks_config_changes(monkeypatch):
    cfg = {"model_size": "small.en", "device": "cpu", "sample_rate": 16000}
    t = Transcriber(cfg)
    assert t.needs_reload() is False  # load() never called: nothing to re-apply

    _install_fake_faster_whisper(monkeypatch)
    t.load()
    assert t.needs_reload() is False  # config matches what was attempted
    cfg["model_size"] = "medium.en"
    assert t.needs_reload() is True  # a settings change is waiting
    cfg["model_size"] = "small.en"
    cfg["device"] = "  AUTO "  # normalization: case/whitespace do not count
    assert t.needs_reload() is True  # cpu -> auto is a real change
    cfg["device"] = " CPU "
    assert t.needs_reload() is False


def _model_dir(root, size):
    d = root / size
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"\0")
    return d


def test_resolve_model_source_prefers_bundled_then_local_then_download(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(gn_transcribe, "_is_frozen", lambda: True)
    monkeypatch.setattr(gn_transcribe, "_resource_base", lambda: bundle)
    monkeypatch.setattr(gn_transcribe, "_writable_model_cache", lambda: cache)

    # Nothing local: frozen builds download into the writable cache.
    source, extra = resolve_model_source("small.en")
    assert source == "small.en" and extra == {"download_root": str(cache)}

    # A model in the writable cache (installer-migrated or hand-placed) loads
    # offline as a local path.
    local = _model_dir(cache, "small.en")
    source, extra = resolve_model_source("small.en")
    assert source == str(local) and extra == {"local_files_only": True}

    # A bundled model still wins over the cache copy.
    bundled = _model_dir(bundle / "models", "small.en")
    source, extra = resolve_model_source("small.en")
    assert source == str(bundled) and extra == {"local_files_only": True}


def test_resolve_model_source_dev_uses_local_dir_or_default_cache(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(gn_transcribe, "_is_frozen", lambda: False)
    monkeypatch.setattr(gn_transcribe, "_writable_model_cache", lambda: cache)

    source, extra = resolve_model_source("small.en")
    assert source == "small.en" and extra == {}  # default HF cache

    local = _model_dir(cache, "small.en")
    source, extra = resolve_model_source("small.en")
    assert source == str(local) and extra == {"local_files_only": True}

    # An empty size never resolves the cache root itself as a "model".
    (cache / "model.bin").write_bytes(b"\0")
    source, extra = resolve_model_source("")
    assert source == "" and extra == {}


def test_needs_reload_after_failed_load_only_on_new_target(monkeypatch):
    # A failed load must NOT report needs_reload for the same target (that
    # would loop), but a corrected target must (recovers from e.g. an empty
    # model size having been applied).
    cfg = {"model_size": "", "device": "cpu", "sample_rate": 16000}
    _install_fake_faster_whisper(monkeypatch, fail_devices=("cpu",))
    t = Transcriber(cfg)
    with pytest.raises(RuntimeError):
        t.load()
    assert t.needs_reload() is False  # same (failing) target: do not loop
    cfg["model_size"] = "small.en"
    assert t.needs_reload() is True  # user fixed the setting: reload is due
