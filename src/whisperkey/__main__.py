"""Entry point.

  python -m whisperkey              run normally
  python -m whisperkey --devices    list microphones
  python -m whisperkey --selftest X transcribe a file (no GUI, no microphone)
  python -m whisperkey --warmup     download/load the model and exit
"""

from __future__ import annotations

import io
import os
import sys

from .config import Config


def _fix_streams() -> None:
    """Keep print alive without a console (pythonw) and keep UTF-8 with one.

    Under pythonw `sys.stdout` is None and the first print raises
    AttributeError; under a console the default cp1252 cannot encode many
    characters.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
        elif isinstance(stream, io.TextIOWrapper):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _devices() -> int:
    from .audio import list_devices

    for idx, name, channels in list_devices():
        print(f"  [{idx}] {name}  ({channels} channels)")
    return 0


def _selftest(path: str, cfg: Config) -> int:
    import numpy as np
    import soundfile as sf

    from .engine import Engine

    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if rate != cfg.samplerate:
        # crude resampling; this test is about the end-to-end path, not quality
        idx = np.linspace(0, len(audio) - 1, int(len(audio) * cfg.samplerate / rate))
        audio = np.interp(idx, np.arange(len(audio)), audio).astype("float32")
    engine = Engine(cfg)
    result = engine.transcribe(audio)
    print(f"language: {result.language}   {result.audio_sec:.1f} s audio / "
          f"{result.elapsed:.1f} s processing")
    print(result.text or "(empty)")
    engine.close()
    return 0 if result.text else 1


def _warmup(cfg: Config) -> int:
    from .engine import Engine

    engine = Engine(cfg)
    engine.load()
    print(f"ready: {engine.backend}")
    engine.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    _fix_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg = Config.load()

    if "--devices" in argv:
        return _devices()
    if "--warmup" in argv:
        return _warmup(cfg)
    if "--selftest" in argv:
        i = argv.index("--selftest")
        if i + 1 >= len(argv):
            print("usage: --selftest <audio-file>")
            return 2
        return _selftest(argv[i + 1], cfg)

    from .app import App

    App(cfg).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
