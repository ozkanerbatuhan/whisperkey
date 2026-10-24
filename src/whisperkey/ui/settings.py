"""The settings window. Two columns, sections split by a hairline, save-apply."""

from __future__ import annotations

import ctypes
import tkinter as tk
from tkinter import ttk

from .. import commands
from ..audio import list_devices
from ..hotkeys import check_hotkey, pretty
from . import theme as T
from .keyfield import KeyField

MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]
DEVICES = ["auto", "cuda", "cpu"]
COMPUTE = ["auto", "int8_float16", "float16", "int8"]
LANGS = ["auto", "en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "tr",
         "ar", "hi", "zh", "ja", "ko"]
PASTE = ["ctrl+v", "shift+insert"]
DEFAULT_MIC = "System default"
VOICE_ACTIONS = [
    ("dictate", "Start dictating"), ("done", "Finish (paste)"),
    ("send", "Finish and press Enter"), ("cancel", "Cancel dictation"),
    ("read", "Start reading"), ("pause", "Pause"), ("resume", "Resume"),
    ("next", "Next chapter"), ("prev", "Previous chapter"),
]


class SettingsWindow:
    def __init__(self, root: tk.Tk, app):
        self.app = app
        self.cfg = app.cfg
        self.win = tk.Toplevel(root)
        self.win.title("whisperkey settings")
        self.win.configure(bg=T.SHELL)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._style()
        self.vars: dict[str, tk.Variable] = {}
        self.keyfields: dict[str, KeyField] = {}
        self._capturing: KeyField | None = None
        self.row = 0
        # two columns: dictation on the left, read-aloud and voice on the right
        outer = tk.Frame(self.win, bg=T.SHELL, padx=22, pady=18)
        outer.pack(fill="both", expand=True)
        self.left = tk.Frame(outer, bg=T.SHELL)
        self.right = tk.Frame(outer, bg=T.SHELL)
        self.foot = tk.Frame(outer, bg=T.SHELL)
        self.left.grid(row=0, column=0, sticky="n")
        self.right.grid(row=0, column=1, sticky="n", padx=(32, 0))
        self.foot.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.foot.columnconfigure(0, weight=1)
        for col in (self.left, self.right):
            col.columnconfigure(1, weight=1, minsize=210)
        self.body = self.left

        self._build()
        self.win.update_idletasks()
        self._dark_titlebar()
        self._center(root)

    # -- appearance

    def _dark_titlebar(self) -> None:
        """Dark title bar; otherwise a light strip sits on top of a dark body."""
        try:
            self.win.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id()) or \
                self.win.winfo_id()
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), 20, ctypes.byref(value), ctypes.sizeof(value))
            # DWM only repaints once it is told the frame changed
            SWP = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(hwnd), None, 0, 0, 0, 0, SWP)
        except Exception:
            pass

    def _style(self) -> None:
        # dropdown lists are Tk, not ttk; their colors come from the option database
        self.win.option_add("*TCombobox*Listbox.background", T.WELL)
        self.win.option_add("*TCombobox*Listbox.foreground", T.INK)
        self.win.option_add("*TCombobox*Listbox.selectBackground", T.RAIL)
        self.win.option_add("*TCombobox*Listbox.selectForeground", T.INK)
        style = ttk.Style(self.win)
        style.theme_use("clam")
        style.configure(
            "d.TCombobox",
            fieldbackground=T.WELL, background=T.WELL, foreground=T.INK,
            arrowcolor=T.INK_DIM, bordercolor=T.RAIL, lightcolor=T.RAIL,
            darkcolor=T.RAIL, selectbackground=T.WELL, selectforeground=T.INK,
        )
        style.map("d.TCombobox", fieldbackground=[("readonly", T.WELL)])

    def _center(self, root: tk.Tk) -> None:
        w, h = self.win.winfo_width(), self.win.winfo_height()
        x = (self.win.winfo_screenwidth() - w) // 2
        y = (self.win.winfo_screenheight() - h) // 3
        self.win.geometry(f"+{x}+{y}")

    # -- row builders

    def _section(self, title: str) -> None:
        pad = (18, 6) if self.row else (0, 6)
        tk.Label(self.body, text=title, bg=T.SHELL, fg=T.INK,
                 font=T.FONT_UI_SEMI, anchor="w").grid(
            row=self.row, column=0, columnspan=2, sticky="w", pady=pad)
        self.row += 1
        tk.Frame(self.body, bg=T.RAIL, height=1).grid(
            row=self.row, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.row += 1

    def _label(self, text: str) -> None:
        tk.Label(self.body, text=text, bg=T.SHELL, fg=T.INK_DIM,
                 font=T.FONT_UI, anchor="w").grid(
            row=self.row, column=0, sticky="w", pady=4, padx=(0, 16))

    def _combo(self, key: str, text: str, values: list[str], value: str) -> None:
        self._label(text)
        var = tk.StringVar(value=value)
        self.vars[key] = var
        ttk.Combobox(self.body, textvariable=var, values=values, state="readonly",
                     style="d.TCombobox", width=24).grid(
            row=self.row, column=1, sticky="ew", pady=4)
        self.row += 1

    def _entry(self, key: str, text: str, value: str, width: int = 26) -> None:
        self._label(text)
        var = tk.StringVar(value=str(value))
        self.vars[key] = var
        tk.Entry(self.body, textvariable=var, width=width, bg=T.WELL, fg=T.INK,
                 insertbackground=T.INK, relief="flat", highlightthickness=1,
                 highlightbackground=T.RAIL, highlightcolor=T.AMBER,
                 font=T.FONT_UI).grid(row=self.row, column=1, sticky="ew", pady=4)
        self.row += 1

    def _keyfield(self, key: str, text: str, value: str, optional: bool = False) -> None:
        self._label(text)
        field = KeyField(self.body, value, self._capture_start, self._capture_cancel)
        field.optional = optional       # Backspace clears it (feature off)
        field.grid(row=self.row, column=1, sticky="ew", pady=4)
        self.keyfields[key] = field
        self.row += 1

    def _slider(self, key: str, text: str, value: float) -> None:
        self._label(text)
        holder = tk.Frame(self.body, bg=T.SHELL)
        holder.grid(row=self.row, column=1, sticky="ew", pady=4)
        var = tk.IntVar(value=int(round(value * 100)))
        self.vars[key] = var
        tk.Scale(
            holder, variable=var, from_=0, to=100, orient="horizontal",
            bg=T.SHELL, fg=T.INK_DIM, troughcolor=T.WELL, activebackground=T.AMBER,
            highlightthickness=0, bd=0, relief="flat", sliderrelief="flat",
            font=T.FONT_UI, length=150, showvalue=True,
        ).pack(side="left")
        tk.Button(
            holder, text="preview", command=self._preview_sound, bg=T.SHELL,
            fg=T.AMBER, activebackground=T.SHELL, activeforeground=T.INK,
            font=T.FONT_UI, relief="flat", bd=0, cursor="hand2",
            highlightthickness=0, padx=10,
        ).pack(side="left", padx=(10, 0))
        self.row += 1

    def _check(self, key: str, text: str, value: bool) -> None:
        var = tk.BooleanVar(value=value)
        self.vars[key] = var
        tk.Checkbutton(
            self.body, text=text, variable=var, bg=T.SHELL, fg=T.INK,
            activebackground=T.SHELL, activeforeground=T.INK, selectcolor=T.WELL,
            font=T.FONT_UI, anchor="w", relief="flat", highlightthickness=0,
            bd=0,
        ).grid(row=self.row, column=0, columnspan=2, sticky="w", pady=3)
        self.row += 1

    # -- content

    def _build(self) -> None:
        cfg = self.cfg

        self._section("Audio and model")
        mics = [DEFAULT_MIC] + [name for _, name, _ in list_devices()]
        current_mic = cfg.input_device or DEFAULT_MIC
        if current_mic not in mics:
            mics.append(current_mic)
        self._combo("input_device", "Microphone", mics, current_mic)
        self._combo("model", "Model", MODELS, cfg.model)
        self._combo("device", "Processor", DEVICES, cfg.device)
        self._combo("compute_type", "Precision", COMPUTE, cfg.compute_type)
        self._combo("language", "Language", LANGS, cfg.language)

        self._section("Memory")
        self._entry("idle_unload_sec", "Idle timeout (s)", cfg.idle_unload_sec, 10)
        self._check("keep_warm", "Keep the model in memory (no wait, RAM stays used)",
                    cfg.keep_warm)

        self._section("Shortcuts")
        self._keyfield("hotkey", "Talk key", cfg.hotkey)
        self._keyfield("lang_key", "Switch language", cfg.lang_key)
        self._keyfield("repaste_key", "Paste again", cfg.repaste_key)
        self._entry("tap_threshold", "Tap threshold (s)", cfg.tap_threshold, 10)

        self._section("Pasting")
        self._combo("paste_keys", "Paste shortcut", PASTE, cfg.paste_keys)
        self._check("restore_clipboard", "Restore the previous clipboard contents",
                    cfg.restore_clipboard)

        self._section("Appearance")
        self._check("overlay", "Show the overlay while talking", cfg.overlay)
        self._entry("overlay_offset", "Overlay height above the bottom (px)",
                    cfg.overlay_offset, 10)
        self._check("beep", "Sound feedback", cfg.beep)
        self._slider("sound_volume", "Volume", cfg.sound_volume)

        self.body, self.row = self.right, 0
        self._section("Read aloud")
        self._keyfield("tts_key", "Read / pause (Backspace = off)", cfg.tts_key, True)
        self._keyfield("tts_prev_key", "Previous chapter", cfg.tts_prev_key, True)
        self._keyfield("tts_next_key", "Next chapter", cfg.tts_next_key, True)
        self._entry("tts_speed", "Speed (0.8-2.5)", cfg.tts_speed, 10)
        self._entry("tts_source", "File to read", cfg.tts_source)

        self._section("Voice commands")
        self._check("voice", "Listen for spoken commands (the microphone stays open)",
                    cfg.voice)
        self._entry("voice_silence", "Silence that ends dictation (s)", cfg.voice_silence, 10)
        self._entry("voice_target", "Type into session (empty = paste)", cfg.voice_target)
        table = {a: list(p) for a, p in commands.DEFAULT_PHRASES.items()}
        table.update(cfg.voice_phrases or {})
        for action, text in VOICE_ACTIONS:
            self._entry(f"phrase:{action}", text, ", ".join(table.get(action, [])))
        tk.Label(self.body, text="Several phrases: separate them with commas.",
                 bg=T.SHELL, fg=T.INK_DIM, font=T.FONT_UI, anchor="w").grid(
            row=self.row, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.row += 1

        self.note = tk.Label(self.foot, text="", bg=T.SHELL, fg=T.AMBER,
                             font=T.FONT_UI, anchor="w")
        self.note.grid(row=0, column=0, sticky="w", pady=(16, 4))

        bar = tk.Frame(self.foot, bg=T.SHELL)
        bar.grid(row=1, column=0, sticky="e", pady=(6, 0))
        self._button(bar, "Close", self.close, T.INK_DIM).pack(side="right", padx=(8, 0))
        self._button(bar, "Save", self.save, T.AMBER).pack(side="right")

    def _button(self, parent, text: str, command, fg: str) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command, bg=T.WELL, fg=fg,
            activebackground=T.RAIL, activeforeground=T.INK, font=T.FONT_UI_SEMI,
            relief="flat", bd=0, padx=18, pady=6, cursor="hand2",
        )

    # -- key capture

    def _capture_start(self, field: KeyField) -> None:
        if self._capturing is not None:
            self.app.cancel_key_capture()
        self._capturing = field
        field.set_capturing(True)
        self.note.configure(text="Press the shortcut - Esc cancels", fg=T.AMBER)
        self.app.begin_key_capture(lambda value: self._captured(field, value))

    def _capture_cancel(self) -> None:
        self.app.cancel_key_capture()

    def _captured(self, field: KeyField, value: str | None) -> None:
        """Arrives through the app's UI queue, not from the hook thread."""
        self._capturing = None
        if value == "backspace" and getattr(field, "optional", False):
            field.value = ""
            field.apply(None)
            self.note.configure(text="Cleared - do not forget to Save", fg=T.AMBER)
            return
        if value in (None, "esc"):
            field.apply(None)
            self.note.configure(text="Cancelled", fg=T.INK_DIM)
            return
        problem = check_hotkey(value)
        if problem:
            field.apply(None)
            self.note.configure(text=problem, fg=T.FAIL)
            return
        field.apply(value)
        self.note.configure(text=f"{pretty(value)} selected - do not forget to Save",
                            fg=T.AMBER)

    def _preview_sound(self) -> None:
        self.app.sounds.set_volume(self.vars["sound_volume"].get() / 100)
        self.app.sounds.preview("done")

    # -- saving

    def save(self) -> None:
        cfg = self.cfg
        old_model = (cfg.model, cfg.device, cfg.compute_type)
        old_keys = (cfg.hotkey, cfg.lang_key, cfg.repaste_key,
                    cfg.tts_key, cfg.tts_prev_key, cfg.tts_next_key)

        keys = {name: field.get() for name, field in self.keyfields.items()}
        used = [v for v in keys.values() if v]
        for name, value in keys.items():
            if not value and self.keyfields[name].optional:
                continue
            problem = check_hotkey(value)
            if problem:
                self.note.configure(text=f"{problem}", fg=T.FAIL)
                return
        if len(set(used)) != len(used):
            self.note.configure(text="The same shortcut cannot do two jobs", fg=T.FAIL)
            return

        mic = self.vars["input_device"].get()
        cfg.input_device = "" if mic == DEFAULT_MIC else mic
        for key in ("model", "device", "compute_type", "language", "paste_keys"):
            setattr(cfg, key, self.vars[key].get().strip())
        for key, value in keys.items():
            setattr(cfg, key, value)
        cfg.sound_volume = self.vars["sound_volume"].get() / 100
        for key in ("keep_warm", "restore_clipboard", "overlay", "beep", "voice"):
            setattr(cfg, key, bool(self.vars[key].get()))
        cfg.tts_source = self.vars["tts_source"].get().strip() or cfg.tts_source
        cfg.voice_target = self.vars["voice_target"].get().strip()
        phrases = {}
        for action, _ in VOICE_ACTIONS:
            items = [p.strip() for p in self.vars[f"phrase:{action}"].get().split(",")]
            items = [p for p in items if p]
            if not items:
                self.note.configure(text=f"Every command needs a phrase ({action})", fg=T.FAIL)
                return
            if items != commands.DEFAULT_PHRASES[action]:
                phrases[action] = items     # only what differs from the defaults is saved
        cfg.voice_phrases = phrases

        errors = []
        for key, cast in (("idle_unload_sec", int), ("overlay_offset", int),
                          ("tap_threshold", float), ("tts_speed", float),
                          ("voice_silence", float)):
            try:
                setattr(cfg, key, cast(self.vars[key].get().replace(",", ".")))
            except ValueError:
                errors.append(key)
        if errors:
            self.note.configure(text="A number is expected: " + ", ".join(errors), fg=T.FAIL)
            return

        cfg.save()
        self.app.apply_settings(
            reload_model=(cfg.model, cfg.device, cfg.compute_type) != old_model,
            rebind=(cfg.hotkey, cfg.lang_key, cfg.repaste_key,
                    cfg.tts_key, cfg.tts_prev_key, cfg.tts_next_key) != old_keys,
        )
        self.note.configure(text="Saved", fg=T.DONE)

    def close(self) -> None:
        if self._capturing is not None:
            self.app.cancel_key_capture()
        self.app.settings_closed()
        self.win.destroy()

    def focus(self) -> None:
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
