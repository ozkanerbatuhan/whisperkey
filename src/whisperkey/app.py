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
from pathlib import Path

import keyboard

from . import commands, console
from .audio import MicError, Recorder
from .config import DATA_DIR, Config
from .engine_proc import EngineProxy
from .hotkeys import Hotkeys, KeyCapture, pretty, split_hotkey
from .listener import Listener
from .paster import copy_only as clip_only
from .paster import paste
from .reading import drop_hallucinations
from .sounds import Sounds
from .speaker import Speaker
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
        # the voice itself loads lazily (warm()), so an unused speaker costs nothing
        self.speaker = Speaker(str(_data_path(cfg.tts_voice)), cfg.tts_source, cfg.tts_speed)
        self.listener: Listener | None = None
        self._voice_dictation = False   # the running dictation was started by voice
        self._voice_started = 0.0
        self._voice_send = False
        self._voice_ended = 0.0         # when the last spoken dictation stopped
        self._send_pending = False      # "send" heard while still transcribing
        self._typed_pid = None          # session typed into without Enter...
        self._typed_at = 0.0            # ...and when
        self._tap_timer: threading.Timer | None = None
        self.overlay.on_seek = lambda f: self._off_ui(self._seek, f)
        self.overlay.on_speed = lambda step: self._off_ui(self._speed, step)
        self.keys = Hotkeys(cfg, self._on_down, self._on_up, self._on_cancel,
                            self.cycle_language, self.repaste, self._speaker_keys)
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

    # ---------------------------------------------------------------- read aloud

    def _speaker_keys(self) -> dict:
        if not self.cfg.tts_key:
            return {}
        return {self.cfg.tts_key: self._on_tts_tap,
                self.cfg.tts_prev_key: lambda: self._chapter(-1),
                self.cfg.tts_next_key: lambda: self._chapter(+1)}

    def _off_ui(self, fn, *args) -> None:
        """Overlay clicks arrive on the UI thread; speaker work may render audio."""
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _chapter(self, step: int) -> None:
        sp = self.speaker
        if sp.state == "idle" and not sp.timeline():
            return
        sp.next_chapter() if step > 0 else sp.prev_chapter()
        self._ui(self._show_reading, 2500 if sp.state == "paused" else None)

    def _seek(self, fraction: float) -> None:
        self.speaker.seek(fraction)
        self._ui(self._show_reading, 2500 if self.speaker.state == "paused" else None)

    def _on_tts_tap(self) -> None:
        """Tap: read / pause / resume. Double tap: media play/pause."""
        timer, self._tap_timer = self._tap_timer, None
        if timer is not None and timer.is_alive():
            timer.cancel()
            keyboard.send("play/pause media")
            return
        self._tap_timer = threading.Timer(self.cfg.double_tap, self._tts_toggle)
        self._tap_timer.start()

    def _tts_toggle(self) -> None:
        state = self.speaker.toggle()
        if state == "paused":
            self._ui(self._show_reading, 2500)
        elif state == "playing":
            self._ui(self._show_reading)

    def _speed(self, step: int) -> None:
        sp = self.speaker
        speed = sp.faster() if step > 0 else sp.slower()
        self.cfg.tts_speed = speed
        self.cfg.save()
        if sp.state != "idle":
            self._ui(self._show_reading, 2500 if sp.state == "paused" else None)

    def _show_reading(self, hide_after: int | None = None) -> None:
        sp = self.speaker
        if not self.cfg.overlay or self.recorder.active or sp.state == "idle":
            return
        elapsed, total = sp.progress()
        title = sp.title
        if len(title) > 26:
            title = title[:25] + "…"
        label = f"{title}  {_clock(elapsed)}/{_clock(total)}" if title else \
            f"{_clock(elapsed)} / {_clock(total)}"
        self.overlay.show_reading(label, elapsed / total if total else 0.0, sp.timeline(),
                                  sp.speed, sp.state == "playing", hide_after)

    def _tick_reading(self) -> None:
        """Runs in the UI pump: keeps the reading bar live, hides it when done."""
        sp = self.speaker
        if sp is None or not self.overlay.reading or self.recorder.active:
            return
        if sp.state == "playing":
            self._show_reading()
        elif sp.state == "idle":
            self.overlay.hide()

    # ---------------------------------------------------------------- voice commands

    def _sync_voice(self) -> None:
        """Start or stop the always-on listener to match `cfg.voice`."""
        commands.configure(self.cfg.voice_phrases)
        if self.cfg.voice and self.listener is None:
            self.speaker.warm()
            self.listener = Listener(str(_data_path(self.cfg.voice_model)), self._on_voice,
                                     log_path=str(DATA_DIR / "voice-log.jsonl"))
            self.speaker.tap = self.listener.feed_far
            self.listener.start()
        elif not self.cfg.voice and self.listener is not None:
            self.speaker.tap = None
            self.listener.stop()
            self.listener = None

    def _on_voice(self, action: str, phrase: str) -> None:
        """A spoken command, from the listener thread."""
        sp = self.speaker
        if action == "dictate":
            if sp.state == "playing":
                sp.pause()
            if self.machine.voice_start() is Action.START:
                self._copy_only = False
                self._voice_dictation = True
                self._voice_started = time.monotonic()
                self._start()
                ends = next(iter(commands.DICTATING), "")
                self._show(f"listening - say '{ends}'", T.LIVE)
        elif action in ("done", "send"):
            if self._voice_dictation or self.machine.recording:
                self._voice_send = action == "send"
                self.machine.voice_stop()
                self._stop()
            elif action == "send":
                self._late_send()
        elif action == "cancel":
            self._voice_dictation = self._voice_send = False
            self._on_cancel()
        elif action == "read":
            if sp.state != "playing":
                sp.toggle()
            self._ui(self._show_reading)
        elif action == "pause":
            sp.pause()
            self._ui(self._show_reading, 2500)
        elif action == "resume":
            if sp.state != "playing":
                sp.toggle()
            self._ui(self._show_reading)
        elif action in ("next", "prev"):
            self._chapter(+1 if action == "next" else -1)

    def _tick_voice(self) -> None:
        """UI pump: tell the listener the state, end a spoken dictation on silence."""
        ls = self.listener
        if ls is None:
            return
        sp = self.speaker
        if self.recorder.active:
            ls.state = "dictating"
        elif sp.state != "idle":
            ls.state = "reading"
        else:
            ls.state = "idle"
        ls.playing_text = sp.sentence if sp.state == "playing" else ""
        if self._voice_dictation and self.recorder.active:
            # give a moment to start talking, then end after `voice_silence` of quiet
            ref = max(ls.last_speech, self._voice_started + 1.5)
            if time.monotonic() - ref > self.cfg.voice_silence:
                self.machine.voice_stop()
                self._stop()

    # ---------------------------------------------------------------- recording

    def _start(self) -> None:
        if self.speaker is not None and self.speaker.state == "playing":
            self.speaker.pause()          # do not talk over the dictation
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
        voice, send = self._voice_dictation, self._voice_send
        self._voice_dictation = self._voice_send = False
        if voice:
            self._voice_ended = time.monotonic()
            self._send_pending = False
            self._typed_pid = None
        self._beep("stop")
        if audio is None or len(audio) / self.cfg.samplerate < self.cfg.min_duration:
            self._hide()
            return
        self._show("transcribing", T.AMBER, busy=True)
        self.jobs.put((audio, self._copy_only, voice, send))

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
            audio, copy_only, voice, send = self.jobs.get()
            if audio is None:
                return
            try:
                result = self.engine.transcribe(audio)
            except Exception as exc:
                self._fail(f"transcription failed: {exc}")
                continue

            # Whisper makes up subtitle credits ("Altyazı M.K.") on trailing silence
            result.text = drop_hallucinations(result.text)
            if self.listener is not None:
                # the closing "Dayı tamam" is heard by Whisper too
                result.text = drop_hallucinations(commands.strip_tail(result.text))
            if not result.text:
                print(f"[whisperkey] no speech found ({result.audio_sec:.1f} s of silence)")
                self._show("no speech", T.FAIL, 1800)
                continue

            self.last_text = result.text
            print(f"[{result.language}] {result.text}   "
                  f"({result.audio_sec:.1f} s audio / {result.elapsed:.1f} s processing)")

            if voice and self.cfg.voice_target:
                # hands-free: typed into the session that answered last, in the
                # background - focus, keyboard and mouse stay with whatever you do
                ok, label = self._deliver_to_session(result.text, send)
            elif copy_only:
                ok = clip_only(result.text)
                label = "copied" if ok else "clipboard locked"
            else:
                ok = paste(result.text, self.cfg.paste_keys, self.cfg.restore_clipboard)
                label = self._preview(result.text) if ok else "clipboard locked"
                if ok and send:
                    time.sleep(0.15)    # let the paste land before Enter
                    keyboard.send("enter")
                    label = f"sent: {label}"
            if ok:
                self._beep("done")
                self._show(label, T.DONE, 1100)
            else:
                self._fail(label)

    SEND_GRACE = 15.0   # s after a spoken dictation in which "send" still applies

    def _late_send(self) -> None:
        """ "Send" after a pause: silence already ended the dictation.

        Still transcribing - the delivery will press Enter. Already typed -
        press Enter in that session now. Anything older is ignored.
        """
        now = time.monotonic()
        if now - self._voice_ended < self.SEND_GRACE:
            if self._typed_pid and self._typed_at >= self._voice_ended:
                if console.type_into(self._typed_pid, "", enter=True):
                    self._beep("done")
                    self._show("sent", T.DONE, 900)
            else:
                self._send_pending = True

    def _deliver_to_session(self, text: str, send: bool) -> tuple[bool, str]:
        pid = console.target(self.cfg.voice_target)
        send = send or self._send_pending
        self._send_pending = False
        if pid and console.type_into(pid, text, enter=send):
            self._typed_pid, self._typed_at = (None if send else pid), time.monotonic()
            return True, ("sent: " if send else "typed: ") + self._preview(text, 36)
        # no live session: keep the words, never type into whatever is in front
        ok = clip_only(text)
        print(f"[voice] no session to type into (pid {pid}); copied instead")
        return ok, "no session - copied" if ok else "clipboard locked"

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
        elif key == "voice":
            self._sync_voice()
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
        if self.cfg.tts_key:
            self.speaker.warm()
        self._sync_voice()
        self.tray.refresh()
        if self.panel.visible:
            self.panel.refresh()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.capture.cancel()
        self.keys.unbind()
        if self.speaker is not None:
            self.speaker.stop()
        if self.listener is not None:
            self.listener.stop()
        self.jobs.put((None, False, False, False))
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
        self._tick_reading()
        self._tick_voice()
        self.root.after(33, self._pump)

    def run(self) -> None:
        self.keys.bind()
        self.tray.start()
        if self.cfg.tts_key:
            self.speaker.warm()
        self._sync_voice()
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


def _clock(seconds: float) -> str:
    seconds = int(seconds + 0.5)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _data_path(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else DATA_DIR / p
