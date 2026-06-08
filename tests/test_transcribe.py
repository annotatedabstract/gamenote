import sys
import types

from gamenote.transcribe import Transcriber, _device_attempts


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
