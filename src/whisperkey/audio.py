"""Microphone recording and live level metering."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd


class MicError(RuntimeError):
    pass


def list_devices() -> list[tuple[int, str, int]]:
    out = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            out.append((idx, dev["name"], dev["max_input_channels"]))
    return out


def resolve_device(name: str):
    """Find the input device matching a name. Empty = system default."""
    if not name:
        return None
    for idx, dev_name, _ in list_devices():
        if name.lower() in dev_name.lower():
            return idx
    print(f"[warning] microphone '{name}' not found; using the default")
    return None


class Recorder:
    """Collects audio block by block. `level` feeds the overlay meter."""

    def __init__(self, samplerate: int = 16000, device: str = ""):
        self.samplerate = samplerate
        self.device = resolve_device(device)
        self._stream = None
        self._frames: list[np.ndarray] = []
        self._level = 0.0
        self._lock = threading.Lock()
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def level(self) -> float:
        """Current level, roughly normalized to 0..1."""
        return self._level

    def _callback(self, indata, frames, time_info, status) -> None:
        # an xrun status is not worth aborting the recording over; the audio
        # is copied either way
        block = indata.copy()
        with self._lock:
            self._frames.append(block)
        rms = float(np.sqrt(np.mean(np.square(block))))
        # log scale: speech typically lands in the 0.01-0.3 RMS range
        self._level = min(1.0, max(0.0, (np.log10(rms + 1e-6) + 2.6) / 2.0))

    def start(self) -> None:
        if self._active:
            return
        with self._lock:
            self._frames = []
        try:
            self._stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=1,
                dtype="float32",
                device=self.device,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise MicError(str(exc)) from exc
        self._active = True

    def _close(self) -> None:
        self._active = False
        self._level = 0.0
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def stop(self) -> np.ndarray | None:
        """End the recording and return what was captured."""
        if not self._active:
            return None
        self._close()
        with self._lock:
            frames, self._frames = self._frames, []
        if not frames:
            return None
        return np.concatenate(frames, axis=0).flatten()

    def cancel(self) -> None:
        self._close()
        with self._lock:
            self._frames = []
