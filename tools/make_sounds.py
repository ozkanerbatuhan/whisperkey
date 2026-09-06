"""Generates the feedback sounds: src/whisperkey/assets/sounds/*.wav

winsound.Beep played square waves, which sounded harsh. These are sine-based
tones with fast-decaying upper harmonics, short (< 120 ms except for the
failure tone). Run it once and commit the output:

    .venv/Scripts/python.exe tools/make_sounds.py
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SR = 44100
OUT = Path(__file__).resolve().parents[1] / "src" / "whisperkey" / "assets" / "sounds"

# harmonic weights: fundamental plus a weak second = a soft wood/bell color
SOFT = (1.0, 0.22, 0.06)
BELL = (1.0, 0.45, 0.18, 0.07)


def note(buf: list[float], at: float, dur: float, f0: float,
         f1: float | None = None, gain: float = 1.0,
         harmonics=SOFT, tau: float = 0.045, attack: float = 0.004) -> None:
    """Add one note to the buffer. With f1 the pitch glides."""
    n = int(dur * SR)
    start = int(at * SR)
    if len(buf) < start + n:
        buf.extend([0.0] * (start + n - len(buf)))
    phase = 0.0
    for i in range(n):
        t = i / SR
        freq = f0 if f1 is None else f0 + (f1 - f0) * (i / max(1, n - 1))
        phase += 2 * math.pi * freq / SR
        env = min(1.0, t / attack) * math.exp(-t / tau)
        # fade to zero over the last 3 ms so there is no click
        tail = dur - t
        if tail < 0.003:
            env *= tail / 0.003
        sample = sum(w * math.sin(phase * (k + 1)) for k, w in enumerate(harmonics))
        buf[start + i] += gain * env * sample / sum(harmonics)


def write(name: str, buf: list[float], peak: float = 0.82) -> None:
    top = max((abs(v) for v in buf), default=1.0) or 1.0
    scale = peak / top
    frames = b"".join(
        struct.pack("<h", int(max(-1.0, min(1.0, v * scale)) * 32767)) for v in buf
    )
    path = OUT / f"{name}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(frames)
    print(f"  {path.name}  {len(buf) / SR * 1000:.0f} ms")


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # start: a short rising glide - the feeling of opening
    buf: list[float] = []
    note(buf, 0.000, 0.090, 587.33, 880.00, tau=0.040)
    write("start", buf)

    # stop: the same glide reversed, a little softer
    buf = []
    note(buf, 0.000, 0.090, 880.00, 587.33, tau=0.038, gain=0.85)
    write("stop", buf)

    # done: a bright two-note bell (B5 -> E6)
    buf = []
    note(buf, 0.000, 0.070, 987.77, harmonics=BELL, tau=0.030)
    note(buf, 0.045, 0.075, 1318.51, harmonics=BELL, tau=0.032, gain=0.9)
    write("done", buf)

    # fail: two low beats - noticeable without being annoying
    buf = []
    note(buf, 0.000, 0.085, 233.08, harmonics=(1.0, 0.3, 0.12), tau=0.050)
    note(buf, 0.100, 0.100, 185.00, harmonics=(1.0, 0.3, 0.12), tau=0.060)
    write("fail", buf)


if __name__ == "__main__":
    print("writing sounds:")
    build()
