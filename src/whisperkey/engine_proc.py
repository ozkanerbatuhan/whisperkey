"""Runs the engine in a separate process.

Why: measured, `Engine.unload()` gives the VRAM back but not the RAM - the
process stays at ~670 MB (the allocator does not return its arena to the OS).
The only reliable way to actually give the memory back is to end the process.

The split: the parent holds the interface and the hotkeys (61 MB, always on);
the engine is born when you speak and dies when it goes idle. The process is
fired the moment recording starts, so model loading overlaps with speech.
"""

from __future__ import annotations

import multiprocessing as mp
import threading
import time
from dataclasses import asdict

from .config import Config
from .engine import Result


def _worker(conn, cfg_dict: dict) -> None:
    """Child process: load the model, wait for work. Exits when the pipe closes."""
    from .engine import Engine

    cfg = Config()
    for key, value in cfg_dict.items():
        if not key.startswith("_"):
            setattr(cfg, key, value)
    cfg.idle_unload_sec = 0  # unloading is handled by killing the process

    try:
        engine = Engine(cfg)
        engine.load()
        conn.send(("ready", engine.backend))
    except Exception as exc:
        conn.send(("fail", f"{exc}"))
        return

    while True:
        try:
            message = conn.recv()
        except (EOFError, OSError):
            return
        if message[0] == "quit":
            return
        if message[0] != "job":
            continue
        _, audio, language = message
        try:
            result = engine.transcribe(audio, language)
            conn.send(("ok", result.text, result.language, result.audio_sec,
                       result.elapsed))
        except Exception as exc:
            conn.send(("fail", f"{exc}"))


class EngineProxy:
    """Manages the child process: starts it on demand, ends it when idle."""

    def __init__(self, cfg: Config, on_state=None):
        self.cfg = cfg
        self.on_state = on_state or (lambda *a: None)
        self._proc: mp.Process | None = None
        self._conn = None
        self._backend = "idle"
        self._lock = threading.RLock()
        self._last_use = 0.0
        self._stop = threading.Event()
        threading.Thread(target=self._idle_watch, daemon=True).start()

    # -- state

    @property
    def loaded(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    @property
    def backend(self) -> str:
        return self._backend if self.loaded else "idle"

    # -- lifecycle

    def start(self) -> None:
        """Start the process and wait for the model. No-op if it is already up."""
        with self._lock:
            if self.loaded:
                self._last_use = time.time()
                return
            self._teardown()
            self.on_state("loading", "loading the model")
            parent, child = mp.Pipe()
            proc = mp.Process(
                target=_worker, args=(child, asdict(self.cfg)),
                name="whisperkey-engine", daemon=True,
            )
            proc.start()
            child.close()
            kind, payload = parent.recv()
            if kind != "ready":
                parent.close()
                proc.terminate()
                raise RuntimeError(payload)
            self._proc, self._conn, self._backend = proc, parent, payload
            self._last_use = time.time()
            # the child's own output never reaches the parent console; report the
            # backend here or a fallback to the CPU passes unnoticed
            print(f"[whisperkey] engine up: {payload} (pid {proc.pid})")

    def start_async(self) -> None:
        """Called when recording starts, so loading overlaps with speech."""
        if self.loaded:
            self._last_use = time.time()
            return
        threading.Thread(target=self._start_quiet, daemon=True).start()

    def _start_quiet(self) -> None:
        try:
            self.start()
        except Exception as exc:
            print(f"[warning] could not start the engine: {exc}")

    def _teardown(self) -> None:
        if self._conn is not None:
            try:
                self._conn.send(("quit",))
            except Exception:
                pass
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self._proc is not None:
            self._proc.join(timeout=2.0)
            if self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(timeout=2.0)
            self._proc = None
        self._backend = "idle"

    def unload(self) -> None:
        with self._lock:
            if self._proc is None:
                return
            self._teardown()
        print("[whisperkey] engine process closed (memory returned)")

    def _idle_watch(self) -> None:
        while not self._stop.wait(5.0):
            if self.cfg.keep_warm or self.cfg.idle_unload_sec <= 0:
                continue
            with self._lock:
                idle = self.loaded and (
                    time.time() - self._last_use > self.cfg.idle_unload_sec
                )
            if idle:
                self.unload()

    def close(self) -> None:
        self._stop.set()
        self.unload()

    # -- work

    def transcribe(self, audio, language: str | None = None) -> Result:
        lang = language if language is not None else self.cfg.language
        audio_sec = len(audio) / self.cfg.samplerate
        with self._lock:
            self.start()
            try:
                self._conn.send(("job", audio, lang))
                reply = self._conn.recv()
            except (EOFError, OSError) as exc:
                self._teardown()
                raise RuntimeError(f"the engine process died: {exc}") from exc
            self._last_use = time.time()
        if reply[0] != "ok":
            raise RuntimeError(reply[1])
        _, text, detected, _, elapsed = reply
        return Result(text=text, language=detected, audio_sec=audio_sec,
                      elapsed=elapsed)
