"""Model loading, warmup, and transcription (lifted from the original daemon's
``load_model`` / ``_warmup`` / ``transcribe``).

The NVIDIA DLL setup must run before ``faster_whisper`` is imported, so it lives
at module import time here. The shipped build targets CPU (int8); the CUDA path
stays as an opt-in fallback for anyone who installs the NVIDIA wheels.
"""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotations only; the real import is lazy in Transcriber.load()
    from faster_whisper import WhisperModel

log = logging.getLogger("gamenote.transcribe")

_NVIDIA_DLL_DIRS: list[str] = []


def _add_nvidia_dll_dirs() -> None:
    """Make the NVIDIA pip-wheel CUDA DLLs loadable for the GPU path. The
    ``nvidia`` package from these wheels is a PEP 420 namespace package (no
    __file__), so we walk __path__ and collect every ``nvidia\\*\\bin`` folder
    (cuBLAS, cuDNN, and any other nvidia-*-cu12 wheels). We both call
    os.add_dll_directory AND prepend those folders to PATH, because CTranslate2
    loads the CUDA libraries through the standard search order at runtime, and
    cuDNN loads its own component DLLs by bare name. The standard search order
    consults PATH but not the os.add_dll_directory user dirs, so PATH is the
    part that actually makes the runtime load succeed. No-op if the wheels are
    absent (the app then uses CPU)."""
    if not sys.platform.startswith("win"):
        return
    try:
        import nvidia
    except Exception:
        return
    dirs = []
    for base in list(getattr(nvidia, "__path__", []) or []):
        try:
            subs = os.listdir(base)
        except Exception:
            continue
        for sub in subs:
            d = os.path.join(base, sub, "bin")
            if os.path.isdir(d):
                dirs.append(d)
    for d in dirs:
        try:
            os.add_dll_directory(d)
        except Exception:
            pass
        _NVIDIA_DLL_DIRS.append(d)
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")


_add_nvidia_dll_dirs()

# numpy loads after the NVIDIA DLL dirs are registered above. faster-whisper is
# imported lazily in Transcriber.load() so that importing this module (for the
# pure _device_attempts logic, or via the controller in tests) does not require
# the heavy backend to be installed.
import numpy as np  # noqa: E402


def nvidia_dll_dirs() -> list[str]:
    return list(_NVIDIA_DLL_DIRS)


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resource_base() -> Path:
    """Where bundled data lives. PyInstaller sets ``sys._MEIPASS`` (the one-file
    temp dir, or the one-folder ``_internal`` dir)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def _writable_model_cache() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home()
    cache = root / "gamenote" / "models"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def resolve_model_source(model_size: str) -> tuple[str, dict]:
    """Decide what to hand WhisperModel.

    - Frozen with the model bundled under ``models/<size>/``: load that path
      offline (``local_files_only``).
    - Frozen without a bundled model: download by name into a writable
      ``%LOCALAPPDATA%\\gamenote\\models`` (never inside the read-only bundle).
    - Dev (not frozen): download by name into the default HF cache.

    Returns ``(model_size_or_path, extra_kwargs)``.
    """
    if _is_frozen():
        bundled = _resource_base() / "models" / model_size
        if (bundled / "model.bin").exists():
            log.info("Using bundled model at %s", bundled)
            return str(bundled), {"local_files_only": True}
        return model_size, {"download_root": str(_writable_model_cache())}
    return model_size, {}


def model_available(model_size: str) -> bool:
    """Best-effort check for whether the model is already present locally (so the
    first run can show a 'downloading model' message). False just means we show
    the download message; the load still works either way."""
    if _is_frozen():
        bundled = _resource_base() / "models" / model_size
        if (bundled / "model.bin").exists():
            return True
    cache = _writable_model_cache()
    if (cache / model_size / "model.bin").exists():
        return True
    try:
        from faster_whisper.utils import _MODELS  # repo id per size, e.g. Systran/...
        repo = _MODELS.get(model_size)
    except Exception:
        repo = None
    if repo:
        folder = cache / ("models--" + repo.replace("/", "--"))
        if folder.exists() and any(folder.rglob("model.bin")):
            return True
    return False


def _device_attempts(device_pref: str) -> list[tuple[str, str]]:
    """Ordered ``(device, compute_type)`` pairs to try, by device preference.

    - ``auto`` (default) and ``cuda``: prefer GPU (float16) and fall back to CPU
      (int8). With ``cuda`` the caller warns the user when the GPU did not
      actually engage, so a missing CUDA install is obvious rather than silently
      slow.
    - ``cpu``: CPU only, which also skips the CUDA probe and its log warning.
    """
    pref = (device_pref or "auto").strip().lower()
    if pref == "cpu":
        return [("cpu", "int8")]
    return [("cuda", "float16"), ("cpu", "int8")]


class Transcriber:
    """Holds the loaded model. ``load()`` is blocking (call it on a background
    thread at startup); ``ready`` reports whether the model is usable."""

    def __init__(self, global_cfg: dict) -> None:
        self.cfg = global_cfg
        self.model: WhisperModel | None = None
        self.device: str = ""
        self.loaded_model_size: str = ""  # remembers what load() actually loaded
        self.loaded_device_pref: str = ""  # the device setting load() honored

    @property
    def ready(self) -> bool:
        return self.model is not None

    def _warmup(self, model: WhisperModel) -> None:
        """One throwaway transcription so the backend initializes now. This
        forces the GPU libraries (cuBLAS / cuDNN) to load, surfacing a
        missing-library failure at launch instead of on the first real note."""
        sample_rate = int(self.cfg["sample_rate"])
        silent = np.zeros(sample_rate, dtype=np.float32)
        list(model.transcribe(silent, language="en", beam_size=1, vad_filter=False)[0])

    def load(self) -> str:
        """Load the model following the configured device preference (see
        ``_device_attempts``). Returns the device actually used. Raises only if
        every configured attempt fails (e.g. a corrupt model, or forced CPU that
        cannot initialize)."""
        from faster_whisper import WhisperModel  # lazy import keeps module load light

        model_size = self.cfg["model_size"]
        device_pref = str(self.cfg.get("device", "auto")).strip().lower()
        source, extra = resolve_model_source(model_size)
        attempts = _device_attempts(device_pref)
        last_exc: Exception | None = None
        for i, (device, compute_type) in enumerate(attempts):
            try:
                m = WhisperModel(source, device=device, compute_type=compute_type, **extra)
                self._warmup(m)
            except Exception as e:
                last_exc = e
                if i + 1 < len(attempts):
                    log.warning("%s path unavailable (%s). Falling back to %s.",
                                device.upper(), e, attempts[i + 1][0].upper())
                else:
                    log.error("%s path unavailable (%s).", device.upper(), e)
                continue
            self.model = m
            self.device = device
            self.loaded_model_size = model_size
            self.loaded_device_pref = device_pref
            log.info("Loaded model '%s' on %s (%s).", model_size, device.upper(), compute_type)
            return device
        raise last_exc if last_exc else RuntimeError("No device attempts configured")

    def transcribe(self, audio: "np.ndarray") -> str:
        if self.model is None:
            raise RuntimeError("Transcriber.transcribe called before load()")
        beam_size = int(self.cfg["beam_size"])
        language = str(self.cfg.get("language", "en")) or "en"
        segments, _ = self.model.transcribe(
            audio, language=language, beam_size=beam_size, vad_filter=False
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
