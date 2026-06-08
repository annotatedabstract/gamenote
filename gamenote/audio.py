"""Microphone capture with energy-based VAD endpointing (lifted from the
original daemon's ``record_note``).

This module does no UI. It records until trailing silence, ``stop_event``, or
``max_seconds``, and returns the captured audio (or None if nothing usable was
heard). A device failure raises :class:`AudioCaptureError` so the caller can
surface a "mic error".
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger("gamenote.audio")


class AudioCaptureError(Exception):
    """Raised when the input stream cannot be opened or read."""


def list_input_devices() -> list[tuple[int, str]]:
    """Return ``(index, name)`` for devices that have input channels. Used by
    the settings GUI device dropdown (Stage 4)."""
    devices = []
    try:
        for i, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                devices.append((i, dev.get("name", f"Device {i}")))
    except Exception as e:
        log.warning("Could not enumerate input devices: %s", e)
    return devices


def record(
    stop_event: threading.Event,
    cfg: dict,
    mode: str = "vad",
    on_rms=None,
    debug: bool = False,
):
    """Record one note. Returns a float32 mono numpy array, or None if no usable
    speech was captured. ``on_rms`` (optional) is called with each frame's RMS
    for the live mic meter; it must not block.

    ``mode`` "vad": speech is anything above ``silence_threshold``; once speech
    has started, ``silence_seconds`` of trailing silence ends the note, and if no
    speech is heard within ``start_grace_seconds`` the press is treated as
    accidental. ``mode`` "toggle": record until ``stop_event`` (the second press)
    or ``max_seconds``, no silence handling.
    """
    sample_rate = int(cfg["sample_rate"])
    frame = int(sample_rate * int(cfg["frame_ms"]) / 1000)
    device = cfg["input_device"]
    silence_threshold = float(cfg["silence_threshold"])
    silence_seconds = float(cfg["silence_seconds"])
    start_grace_seconds = float(cfg["start_grace_seconds"])
    min_seconds = float(cfg["min_seconds"])
    max_seconds = float(cfg["max_seconds"])

    frames = []
    speech_started = False
    silence_run = 0.0
    elapsed = 0.0
    frame_dur = frame / sample_rate

    def _open(dev):
        return sd.InputStream(
            samplerate=sample_rate, channels=1, dtype="float32", blocksize=frame, device=dev
        )

    # Open the configured device; if it is gone (unplugged / reindexed), fall
    # back to the system default rather than just failing.
    try:
        stream = _open(device)
    except Exception as e:
        if device is None:
            log.error("Could not open input stream: %s", e)
            raise AudioCaptureError(str(e)) from e
        log.warning("Input device %r unavailable (%s); using the system default.", device, e)
        try:
            stream = _open(None)
        except Exception as e2:
            log.error("Could not open default input stream: %s", e2)
            raise AudioCaptureError(str(e2)) from e2

    try:
        with stream:
            while True:
                if stop_event.is_set():
                    break
                block, _ = stream.read(frame)
                frames.append(block.copy())
                elapsed += frame_dur

                rms = float(np.sqrt(np.mean(np.square(block))))
                if on_rms is not None:
                    on_rms(rms)
                if debug:
                    log.debug("rms=%.5f elapsed=%.2f speech=%s", rms, elapsed, speech_started)

                if elapsed >= max_seconds:
                    break

                if mode == "vad":
                    if rms > silence_threshold:
                        speech_started = True
                        silence_run = 0.0
                    elif speech_started:
                        silence_run += frame_dur
                        if silence_run >= silence_seconds:
                            break
                    elif elapsed >= start_grace_seconds:
                        break  # never heard speech; treat as an accidental press
    except Exception as e:
        log.error("Audio capture failed: %s", e)
        raise AudioCaptureError(str(e)) from e

    if not frames:
        return None
    audio = np.concatenate(frames, axis=0).flatten().astype(np.float32)
    if len(audio) / sample_rate < min_seconds:
        return None
    if mode == "vad" and not speech_started:
        return None  # accidental press; in toggle the user recorded on purpose
    return audio
