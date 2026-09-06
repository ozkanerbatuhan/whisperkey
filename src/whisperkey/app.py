"""The glue: hotkey -> record -> transcribe -> paste, and feeding the UI.

Thread layout:
  main thread  tkinter (overlay, settings) - all UI work goes through it
  tray thread  pystray
  hook thread  keyboard callbacks
  worker       single consumer: transcription and pasting, keeps speech order

No other thread touches the UI; everything is handed to the main thread
through `ui_q`.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk

from .audio import MicError, Recorder
from .config import Config
from .engine_proc import EngineProxy
from .hotkeys import Hotkeys, KeyCapture, pretty, split_hotkey
from .paster import copy_only as clip_only
from .paster import paste
from .sounds import Sounds
from .states import Action, Mode, PttMachine
from .ui import theme as T
from .ui.overlay import Overlay
from .ui.panel import Panel
from .ui.settings import SettingsWindow
from .ui.tray import Tray


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ui_q: queue.Queue = queue.Queue()
        self.jobs: queue.Queue = queue.Queue()
        self.last_text = ""
        self._copy_only = False
        self._settings = None
        self._quitting = False

        self.root = tk.Tk()
        self.root.withdraw()

        self.overlay = Overlay(self.root, cfg.overlay_offset)
        self.overlay.set_language(cfg.language)
        self.panel = Panel(self.root, self)
        self.sounds = Sounds(cfg.beep, cfg.sound_volume)

        self.machine = PttMachine(cfg.tap_threshold)
        self.recorder = Recorder(cfg.samplerate, cfg.input_device)
        self.engine = EngineProxy(cfg, on_state=self._engine_state)
        self.tray = Tray(self)
        self.keys = Hotkeys(cfg, self._on_down, self._on_up, self._on_cancel,
                            self.cycle_language, self.repaste)
        self.capture = KeyCapture()

        threading.Thread(target=self._worker, daemon=True).start()

    # ---------------------------------------------------------------- helpers

    def _beep(self, kind: str) -> None:
        self.sounds.play(kind)

    def _ui(self, fn, *args) -> None:
        """Queue a UI call for the main thread."""
        self.ui_q.put((fn, args))

    # the public face of the UI queue: used by the tray and hook threads
    post_ui = _ui

    def _show(self, text: str, color: str, hide_after: int | None = None,
              busy: bool = False) -> None:
        if self.cfg.overlay:
            self._ui(self.overlay.show, text, color, hide_after, busy)
        self._ui(self.tray.set_accent, color)
        self._ui(self.tray.set_tooltip, text)
        self._ui(self.panel.set_status, text, color)

    def _hide(self) -> None:
        self._ui(self.overlay.hide)
        self._ui(self.tray.set_accent, T.INK_DIM)
        self._ui(self.tray.set_tooltip, "ready")
        self._ui(self.panel.set_status, "ready", T.INK_DIM)

    def status_line(self) -> str:
        state = "listening" if self.recorder.active else "ready"
        memory = self.engine.backend
        return f"{state} - language {self.cfg.language}, engine {memory}"

    # ---------------------------------------------------------------- hotkeys

    def _on_down(self) -> None:
        action = self.machine.key_down(time.time())
        if action is Action.START:
            # if the shortcut itself contains Ctrl, Ctrl no longer means copy-only
            mods, _ = split_hotkey(self.cfg.hotkey)
            self._copy_only = "ctrl" not in mods and Hotkeys.ctrl_held()
            self._start()
        elif action is Action.STOP:
            self._stop()

    def _on_up(self) -> None:
        action = self.machine.key_up(time.time())
        if action is Action.STOP:
            self._stop()
        elif self.machine.mode is Mode.TOGGLE:
            self._show(f"listening ({pretty(self.cfg.hotkey)} ends it)", T.LIVE)

    def _on_cancel(self) -> None:
        if self.machine.cancel() is Action.CANCEL:
            self.recorder.cancel()
            self._beep("stop")
            self._show("cancelled", T.INK_DIM, 700)

    # ---------------------------------------------------------------- recording

    def _start(self) -> None:
        try:
            self.recorder.start()
        except MicError as exc:
            self.machine.cancel()
            self._fail(f"microphone did not open: {exc}")
            return
        # fire the process now so loading overlaps with speech
        self.engine.start_async()
        self._beep("start")
        label = "copying" if self._copy_only else "listening"
        self._show(label, T.LIVE)

    def _stop(self) -> None:
        audio = self.recorder.stop()
        self._beep("stop")
        if audio is None or len(audio) / self.cfg.samplerate < self.cfg.min_duration:
            self._hide()
            return
        self._show("transcribing", T.AMBER, busy=True)
        self.jobs.put((audio, self._copy_only))

    def _fail(self, message: str) -> None:
        # the overlay disappears after 2.5 s; keep the reason in the console
        print(f"[error] {message}")
        self._beep("fail")
        self._show(message, T.FAIL, 2500)

    # ---------------------------------------------------------------- worker

    def _engine_state(self, kind: str, message: str) -> None:
        if kind == "loading":
            self._show("warming up", T.AMBER, busy=True)

    def _worker(self) -> None:
        while True:
            audio, copy_only = self.jobs.get()
            if audio is None:
                return
            try:
                result = self.engine.transcribe(audio)
            except Exception as exc:
                self._fail(f"transcription failed: {exc}")
                continue

            if not result.text:
                print(f"[whisperkey] no speech found ({result.audio_sec:.1f} s of silence)")
                self._show("no speech", T.FAIL, 1800)
                continue

            self.last_text = result.text
            print(f"[{result.language}] {result.text}   "
                  f"({result.audio_sec:.1f} s audio / {result.elapsed:.1f} s processing)")

            if copy_only:
                ok = clip_only(result.text)
                label = "copied" if ok else "clipboard locked"
            else:
                ok = paste(result.text, self.cfg.paste_keys, self.cfg.restore_clipboard)
                label = self._preview(result.text) if ok else "clipboard locked"

            if ok:
                self._beep("done")
                self._show(label, T.DONE, 1100)
            else:
                self._fail(label)

    @staticmethod
    def _preview(text: str, limit: int = 44) -> str:
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    # ---------------------------------------------------------------- commands

    def cycle_language(self) -> None:
        order = list(self.cfg.language_cycle) or ["auto"]
        try:
            nxt = order[(order.index(self.cfg.language) + 1) % len(order)]
        except ValueError:
            nxt = order[0]
        self.cfg.language = nxt
        self.cfg.save()
        self._ui(self.overlay.set_language, self.cfg.language)
        self._ui(self.tray.refresh)
        self._show(f"language: {self.cfg.language}", T.AMBER, 900)

    def set_language(self, code: str) -> None:
        self.cfg.language = code
        self.cfg.save()
        self._ui(self.overlay.set_language, code)
        self._ui(self.tray.refresh)

    def repaste(self) -> None:
        if not self.last_text:
            return
        if paste(self.last_text, self.cfg.paste_keys, self.cfg.restore_clipboard):
            self._show(self._preview(self.last_text), T.DONE, 900)

    def toggle_keep_warm(self) -> None:
        self.cfg.keep_warm = not self.cfg.keep_warm
        self.cfg.save()
        if self.cfg.keep_warm:
            self.engine.start_async()
        self._ui(self.tray.refresh)

    def unload_model(self) -> None:
        threading.Thread(target=self.engine.unload, daemon=True).start()

    # ---------------------------------------------------------------- panel

    def toggle_panel(self) -> None:
        """Left click on the tray. The tray runs on its own thread, so queue it."""
        self._ui(self.panel.toggle)

    def apply_quick_setting(self, key: str) -> None:
        """A single setting flipped from the panel - applied without a window."""
        if key == "beep":
            self.sounds.enabled = self.cfg.beep
        elif key == "overlay" and not self.cfg.overlay:
            self.overlay.hide()
        self.tray.refresh()

    # ---------------------------------------------------------- key capture

    def begin_key_capture(self, on_done) -> None:
        """Read the next key press.

        Global hooks are removed while this runs - otherwise the key being
        captured would start a recording at the same time.
        """
        self.keys.unbind()

        def finished(value):
            self.keys.bind()
            self._ui(on_done, value)

        self.capture.start(finished)

    def cancel_key_capture(self) -> None:
        self.capture.cancel()

    def open_settings(self) -> None:
        self._ui(self._open_settings_main)

    def _open_settings_main(self) -> None:
        if self._settings is not None:
            self._settings.focus()
            return
        self._settings = SettingsWindow(self.root, self)

    def settings_closed(self) -> None:
        self._settings = None

    def apply_settings(self, reload_model: bool, rebind: bool) -> None:
        self.machine.tap_threshold = self.cfg.tap_threshold
        self.overlay.offset = self.cfg.overlay_offset
        self.overlay.set_language(self.cfg.language)
        self.sounds.enabled = self.cfg.beep
        self.sounds.set_volume(self.cfg.sound_volume)
        self.recorder = Recorder(self.cfg.samplerate, self.cfg.input_device)
        if reload_model:
            threading.Thread(target=self.engine.unload, daemon=True).start()
        if rebind:
            self.keys.unbind()
            self.keys.bind()
        self.tray.refresh()
        if self.panel.visible:
            self.panel.refresh()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.capture.cancel()
        self.keys.unbind()
        self.jobs.put((None, False))
        self.engine.close()
        self.tray.stop()
        self._ui(self.root.quit)

    # ---------------------------------------------------------------- loop

    def _pump(self) -> None:
        while True:
            try:
                fn, args = self.ui_q.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception as exc:
                print(f"[warning] could not update the interface: {exc}")
        if self.recorder.active and self.cfg.overlay:
            self.overlay.set_level(self.recorder.level)
        self.root.after(33, self._pump)

    def run(self) -> None:
        self.keys.bind()
        self.tray.start()
        if self.cfg.keep_warm:
            self.engine.start_async()
        print(
            f"\n  whisperkey is running. Left click the tray icon for "
            f"the panel, right click for the menu.\n"
            f"  Hold {pretty(self.cfg.hotkey)} and talk; it is pasted when "
            f"you let go.\n"
            f"  A short tap turns on hands-free mode, Esc cancels.\n"
            f"  {pretty(self.cfg.lang_key)} switches language, "
            f"{pretty(self.cfg.repaste_key)} pastes the last text again.\n"
        )
        self.root.after(33, self._pump)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            self.quit()
            sys.stdout.flush()
