"""The Whisper engine: loads the model and turns audio into text.

The idle policy does not live here - `unload()` gives the VRAM back but the
process still holds ~670 MB of RAM (measured). The layer that really returns
memory is `engine_proc.EngineProxy`: it keeps the engine in its own process
and terminates it.
"""

from __future__ import annotations

import gc
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import MODEL_DIR, Config


@dataclass
class Result:
    text: str
    language: str
    audio_sec: float
    elapsed: float


def _enable_cuda_dlls() -> None:
    """Put the pip-installed cuBLAS/cuDNN DLLs where CTranslate2 can see them.

    Without them CUDA silently fails to start and we fall back to the CPU with
    no visible reason why.
    """
    try:
        import nvidia
    except ImportError:
        return
    # nvidia is a namespace package: no __file__, but it has __path__
    bins = [p for root in nvidia.__path__ for p in Path(root).glob("*/bin")]
    for path in bins:
        try:
            os.add_dll_directory(str(path))
        except OSError:
            pass
    if bins:
        os.environ["PATH"] = os.pathsep.join(
            [str(p) for p in bins] + [os.environ.get("PATH", "")]
        )


def cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def free_vram_mb() -> float:
    """Free memory on the GPU. -1 if it cannot be queried."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip()
        used, total = (float(x) for x in out.splitlines()[0].split(","))
        return total - used
    except Exception:
        return -1.0


class Engine:
    def __init__(self, cfg: Config, on_state=None):
        self.cfg = cfg
        self.on_state = on_state or (lambda *a: None)
        self._model = None
        self._lock = threading.RLock()
        self._last_use = 0.0
        self._device = "?"
        self._compute = "?"
        _enable_cuda_dlls()

    # -- state

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def backend(self) -> str:
        return f"{self._device}/{self._compute}" if self.loaded else "idle"

    # -- loading

    def _pick_backend(self) -> tuple[str, str]:
        """A measured choice (large-v3-turbo, RTX 3050 Ti):

          float16        2243 MB VRAM, 5.4 s load
          int8_float16   1187 MB VRAM, 9.4 s load

        Transcription speed is the same either way. With room to spare we take
        float16 - it halves the load time; on a busy GPU (a game, 3D CAD) we
        drop to the smaller one.
        """
        device = self.cfg.device
        compute = self.cfg.compute_type
        if device == "auto":
            device = "cuda" if cuda_available() else "cpu"
        if compute == "auto":
            if device != "cuda":
                compute = "int8"
            else:
                compute = "float16" if free_vram_mb() >= 3000 else "int8_float16"
        return device, compute

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                self._last_use = time.time()
                return

            device, compute = self._pick_backend()
            self.on_state("loading", f"loading the model ({device})")
            t0 = time.time()
            try:
                model = self._open(device, compute)
            except Exception as exc:
                if device != "cuda":
                    raise
                # not enough VRAM: try lower precision, then the CPU
                print(f"[warning] {compute} did not start ({exc})")
                try:
                    compute = "int8_float16"
                    model = self._open(device, compute)
                except Exception as exc2:
                    print(f"[warning] CUDA did not start ({exc2}); falling back to the CPU")
                    device, compute = "cpu", "int8"
                    model = self._open(device, compute)
            self._model = model
            self._device, self._compute = device, compute
            self._last_use = time.time()
            print(f"[whisperkey] model ready: {self.cfg.model} {device}/{compute} "
                  f"({time.time() - t0:.1f} s)")

    def _open(self, device: str, compute: str):
        """Open the model. Local files first - keeps it from hanging when offline."""
        from faster_whisper import WhisperModel

        try:
            return WhisperModel(self.cfg.model, device=device, compute_type=compute,
                                download_root=str(MODEL_DIR), local_files_only=True)
        except Exception:
            print(f"[whisperkey] downloading {self.cfg.model}...")
            return WhisperModel(self.cfg.model, device=device, compute_type=compute,
                                download_root=str(MODEL_DIR))

    def unload(self) -> None:
        with self._lock:
            if self._model is None:
                return
            self._model = None
            self._device = self._compute = "?"
        gc.collect()
        print("[whisperkey] model released (VRAM returned)")

    def close(self) -> None:
        self.unload()

    # -- transcription

    def transcribe(self, audio, language: str | None = None) -> Result:
        lang = language if language is not None else self.cfg.language
        lang = None if lang == "auto" else lang
        audio_sec = len(audio) / self.cfg.samplerate
        self.load()
        t0 = time.time()
        with self._lock:
            segments, info = self._model.transcribe(
                audio,
                language=lang,
                beam_size=self.cfg.beam_size,
                vad_filter=self.cfg.vad,
                condition_on_previous_text=False,
                initial_prompt=self.cfg.initial_prompt or None,
            )
            text = "".join(s.text for s in segments).strip()
            self._last_use = time.time()
        return Result(
            text=text,
            language=getattr(info, "language", "?") or "?",
            audio_sec=audio_sec,
            elapsed=time.time() - t0,
        )
