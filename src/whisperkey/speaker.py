"""Read text aloud with a local Piper voice: play, pause, seek, chapters, speed.

The text comes from a file (`tts_source`) that something else keeps writing -
for example a Claude Code Stop hook that saves the last answer. One key
toggles play/pause; when the file has changed since the last reading, the
next press starts the new text from the top. Headings and bold-label
paragraphs become chapters, like the chapters of a video.

Thread layout:
  caller       toggle()/faster()/slower() - from the hook thread, kept short
  synth        one background thread renders sentences in order
  audio        sounddevice callback pulls samples from the current sentence

Speed changes re-render the current sentence and jump to the same relative
position, so the change is heard at once instead of at the next sentence.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

from .reading import chapters, sentences

SPEED_MIN, SPEED_MAX, SPEED_STEP = 0.8, 2.5, 0.1
SECONDS_PER_CHAR = 0.065        # rough estimate at 1x until a sentence is rendered


class Speaker:
    def __init__(self, voice_path: str, source: str, speed: float = 1.5,
                 device: str | None = None):
        self.voice_path = voice_path
        self.source = Path(source).expanduser()
        self.speed = speed
        self.device = device
        self._voice = None
        self._load_lock = threading.Lock()
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)

        self._parts: list[str] = []
        self._starts: list[int] = []    # first sentence of each chapter
        self._titles: list[str] = []
        self._audio: list[np.ndarray | None] = []
        self._idx = 0                   # sentence being played
        self._pos = 0                   # sample offset inside it
        self._gen = 0                   # bumps on new text / speed change
        self._mtime = 0.0
        self._stream = None
        self.state = "idle"             # idle | playing | paused
        self.tap = None                 # tap(samples, rate): what was just played (echo reference)
        threading.Thread(target=self._synth_loop, daemon=True).start()

    # ------------------------------------------------------------ voice

    def warm(self) -> None:
        """Load the voice and render one word; the first real call is then fast."""
        threading.Thread(target=self._voice_ready, daemon=True).start()

    def _voice_ready(self):
        with self._load_lock:
            if self._voice is None:
                from piper import PiperVoice

                self._voice = PiperVoice.load(self.voice_path)
                for _ in self._voice.synthesize("hazır"):
                    pass
        return self._voice

    @property
    def rate(self) -> int:
        return self._voice_ready().config.sample_rate

    def _render(self, text: str, speed: float) -> np.ndarray:
        from piper import SynthesisConfig

        cfg = SynthesisConfig(length_scale=1.0 / speed)
        chunks = [c.audio_int16_array for c in self._voice_ready().synthesize(text, syn_config=cfg)]
        audio = np.concatenate(chunks) if chunks else np.zeros(0, np.int16)
        # a short breath between sentences
        return np.concatenate([audio, np.zeros(int(self.rate * 0.12 / speed), np.int16)])

    def _synth_loop(self) -> None:
        while True:
            with self._wake:
                while (todo := self._next_missing()) is None:
                    self._wake.wait()
                gen, speed, text = self._gen, self.speed, self._parts[todo]
            audio = self._render(text, speed)
            with self._lock:
                if gen == self._gen and todo < len(self._audio):
                    self._audio[todo] = audio

    def _next_missing(self) -> int | None:
        for i in range(self._idx, len(self._audio)):
            if self._audio[i] is None:
                return i
        return None

    # ------------------------------------------------------------ playback

    def _callback(self, out, frames, _time, _status) -> None:
        out.fill(0)
        filled = 0
        with self._lock:
            while filled < frames and self._idx < len(self._parts):
                cur = self._audio[self._idx]
                if cur is None:
                    break               # renderer is behind; silence for now
                take = min(frames - filled, len(cur) - self._pos)
                out[filled:filled + take, 0] = cur[self._pos:self._pos + take]
                filled += take
                self._pos += take
                if self._pos >= len(cur):
                    self._idx += 1
                    self._pos = 0
                    self._wake.notify()
            done = self._idx >= len(self._parts)
        if self.tap is not None and filled:
            self.tap(out[:filled, 0], self._rate_or_default())
        if done:
            self.state = "idle"
            raise sd.CallbackStop

    def _open_stream(self) -> None:
        self._close_stream()
        self._stream = sd.OutputStream(samplerate=self.rate, channels=1, dtype="int16",
                                       device=self.device, callback=self._callback,
                                       blocksize=1024)
        self._stream.start()

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------ commands

    def _source_mtime(self) -> float:
        try:
            return self.source.stat().st_mtime
        except OSError:
            return 0.0

    def toggle(self) -> str:
        """Play / pause / resume. A newer source file restarts from the top."""
        fresh = self._source_mtime() > self._mtime
        if self.state == "playing":
            self.pause()
        elif self.state == "paused" and not fresh:
            self.resume()
        else:
            self.start()
        return self.state

    def start(self) -> None:
        try:
            raw = self.source.read_text(encoding="utf-8")
        except OSError:
            raw = ""
        parts, starts, titles = [], [], []
        for title, body in chapters(raw):
            lines = sentences(body)
            if not lines:
                lines = [title]
            starts.append(len(parts))
            titles.append(title)
            parts += lines
        if not parts:
            return
        with self._wake:
            self._mtime = self._source_mtime()
            self._gen += 1
            self._parts = parts
            self._starts, self._titles = starts, titles
            self._audio = [None] * len(parts)
            self._idx = self._pos = 0
            self.state = "playing"
            self._wake.notify()
        self._open_stream()

    def pause(self) -> None:
        if self.state == "playing":
            self.state = "paused"
            self._close_stream()

    def resume(self) -> None:
        if self.state == "paused":
            self.state = "playing"
            self._open_stream()

    def stop(self) -> None:
        self.state = "idle"
        self._close_stream()

    def faster(self) -> float:
        return self.set_speed(self.speed + SPEED_STEP)

    def slower(self) -> float:
        return self.set_speed(self.speed - SPEED_STEP)

    def set_speed(self, speed: float) -> float:
        speed = round(max(SPEED_MIN, min(SPEED_MAX, speed)), 2)
        if speed == self.speed:
            return speed
        with self._lock:
            idx = self._idx
            cur = self._audio[idx] if idx < len(self._audio) else None
            frac = self._pos / len(cur) if cur is not None and len(cur) else 0.0
            self.speed = speed
            self._gen += 1
            busy = idx < len(self._parts)
            text = self._parts[idx] if busy else ""
        if not busy:
            return speed
        # render the current sentence right here so the change is heard at once
        audio = self._render(text, speed)
        with self._wake:
            self._audio = [None] * len(self._parts)
            if self._idx == idx:
                self._audio[idx] = audio
                self._pos = int(frac * len(audio))
            self._wake.notify()
        return speed

    # ------------------------------------------------------------ chapters / seek

    def _jump(self, idx: int) -> None:
        """Move to the start of sentence `idx` (sentence granularity is enough)."""
        with self._wake:
            if not self._parts:
                return
            self._idx = max(0, min(len(self._parts) - 1, idx))
            self._pos = 0
            self._wake.notify()
            finished = self.state == "idle"
        if finished:                    # jumping back into a finished text replays it
            self.state = "playing"
            self._open_stream()

    def chapter(self) -> int:
        with self._lock:
            return max([c for c, s in enumerate(self._starts) if s <= self._idx], default=0)

    def next_chapter(self) -> None:
        c = self.chapter()
        if c + 1 < len(self._starts):
            self._jump(self._starts[c + 1])

    def prev_chapter(self) -> None:
        """Back to the start of this chapter; again within 2 s - the previous one."""
        c = self.chapter()
        durs = self._durations()
        into = sum(durs[self._starts[c]:self._idx]) + self._pos / self._rate_or_default()
        self._jump(self._starts[c - 1] if into < 2.0 and c > 0 else self._starts[c])

    def seek(self, fraction: float) -> None:
        durs = self._durations()
        target, t = fraction * sum(durs), 0.0
        for i, d in enumerate(durs):
            if t + d > target:
                self._jump(i)
                return
            t += d

    # ------------------------------------------------------------ progress

    def _rate_or_default(self) -> int:
        return self._voice.config.sample_rate if self._voice else 22050

    def _durations(self) -> list[float]:
        """Seconds per sentence at the current speed; unrendered ones are estimated."""
        with self._lock:
            rate = self._rate_or_default()
            done = [(len(a), len(p)) for a, p in zip(self._audio, self._parts, strict=True)
                    if a is not None]
            per_char = (sum(a for a, _ in done) / rate / sum(c for _, c in done)) if done \
                else SECONDS_PER_CHAR / self.speed
            return [len(a) / rate if a is not None else len(p) * per_char
                    for a, p in zip(self._audio, self._parts, strict=True)]

    def progress(self) -> tuple[float, float]:
        """(elapsed, total) seconds of the current text at the current speed."""
        with self._lock:
            durs = self._durations()
            elapsed = sum(durs[:self._idx]) + self._pos / self._rate_or_default()
            return elapsed, sum(durs)

    def timeline(self) -> list[tuple[float, float, str]]:
        """Chapters as (start, end, title) fractions of the whole text."""
        with self._lock:
            durs = self._durations()
            total = sum(durs) or 1.0
            ends = self._starts[1:] + [len(durs)]
            return [(sum(durs[:s]) / total, sum(durs[:e]) / total, t)
                    for s, e, t in zip(self._starts, ends, self._titles, strict=True)]

    @property
    def sentence(self) -> str:
        """The sentence being read now and the one before (for the echo check:
        a recognizer reports a word only after it ended, by then the reading
        may have moved on)."""
        with self._lock:
            return " ".join(self._parts[max(0, self._idx - 1):self._idx + 1])

    @property
    def title(self) -> str:
        with self._lock:
            return self._titles[self.chapter()] if self._titles else ""


def _demo() -> None:
    """python -m whisperkey.speaker <voice.onnx> <text-file>: read it, Ctrl+C to stop."""
    import sys

    sp = Speaker(sys.argv[1], sys.argv[2])
    t = time.time()
    sp.start()
    while sp.state != "idle":
        time.sleep(0.2)
        e, tot = sp.progress()
        print(f"\r{e:5.1f} / {tot:5.1f} s", end="")
    print(f"\ndone in {time.time() - t:.1f} s")


if __name__ == "__main__":
    _demo()
