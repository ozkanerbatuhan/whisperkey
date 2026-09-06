"""Feedback sounds.

`winsound.Beep` produced square waves, which is why it sounded harsh. The
sounds now live in `assets/sounds/*.wav` inside the package; they are read
into memory once and played with SND_MEMORY, so the disk is not touched on
every play and the volume is scaled without rewriting the file.

If a file is missing it falls back to the old tones: a harsh sound beats no
sound at all.
"""


from __future__ import annotations

import io
import threading
import wave
import winsound
from array import array
from pathlib import Path

SOUND_DIR = Path(__file__).resolve().parent / "assets" / "sounds"
KINDS = ("start", "stop", "done", "fail")

# fallback: square-wave tones played when a wav is missing (old behavior)
TONES = {"start": (880, 60), "stop": (620, 60), "done": (1320, 45), "fail": (300, 180)}

_FLAGS = winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT


def _scaled(path: Path, volume: float) -> bytes:
    """Read a wav, scale its samples, return it as a wav again."""
    with wave.open(str(path), "rb") as src:
        params = src.getparams()
        frames = src.readframes(params.nframes)
    if params.sampwidth == 2 and volume != 1.0:
        samples = array("h")
        samples.frombytes(frames)
        for i, value in enumerate(samples):
            samples[i] = max(-32768, min(32767, int(value * volume)))
        frames = samples.tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as dst:
        dst.setparams(params)
        dst.writeframes(frames)
    return buf.getvalue()


class Sounds:
    """Short feedback sounds. Callable from any thread; playback is async."""

    def __init__(self, enabled: bool = True, volume: float = 0.7,
                 directory: Path = SOUND_DIR):
        self.dir = directory
        self.enabled = enabled
        self._volume = 1.0
        self._cache: dict[str, bytes | None] = {}
        self.set_volume(volume)

    @property
    def volume(self) -> float:
        return self._volume

    def set_volume(self, volume: float) -> None:
        volume = max(0.0, min(1.0, float(volume)))
        if volume != self._volume:
            self._cache.clear()
        self._volume = volume

    def available(self) -> bool:
        """Are the wavs in place - the settings window reports this."""
        return all((self.dir / f"{k}.wav").exists() for k in KINDS)

    def _data(self, kind: str) -> bytes | None:
        if kind not in self._cache:
            path = self.dir / f"{kind}.wav"
            try:
                self._cache[kind] = _scaled(path, self._volume)
            except Exception as exc:
                print(f"[warning] could not play {path.name} ({exc}); falling back to a tone")
                self._cache[kind] = None
        return self._cache[kind]

    def play(self, kind: str) -> None:
        if not self.enabled or kind not in TONES:
            return
        data = self._data(kind)
        if data is not None:
            try:
                winsound.PlaySound(data, _FLAGS)
                return
            except Exception:
                self._cache[kind] = None
        self._fallback(kind)

    def _fallback(self, kind: str) -> None:
        # Beep is synchronous; the caller may be the hook thread, do not block it
        freq, dur = TONES[kind]

        def beep() -> None:
            try:
                winsound.Beep(freq, dur)
            except RuntimeError:
                pass

        threading.Thread(target=beep, daemon=True).start()

    def preview(self, kind: str = "done") -> None:
        """The settings window's "preview" - plays even when sounds are off."""
        was, self.enabled = self.enabled, True
        try:
            self.play(kind)
        finally:
            self.enabled = was
