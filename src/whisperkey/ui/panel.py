"""The mini panel that opens on a left click in the tray.

Not a shrunken settings window: it opens next to the cursor, fits one screen
and closes when it loses focus. The three things you touch often live here -
language, sounds, overlay - the rest stays in Settings.
"""

from __future__ import annotations

import time
import tkinter as tk

from ..hotkeys import pretty
from . import theme as T

MARGIN = 12
TASKBAR = 56          # keep the panel off the taskbar when the cursor is on it


class Panel:
    """Every call must come from the tkinter main thread."""

    def __init__(self, root: tk.Tk, app):
        self.root = root
        self.app = app
        self.cfg = app.cfg
        self.visible = False
        self._closed_at = 0.0
        self._status = ("ready", T.INK_DIM)

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=T.RAIL)          # a 1 px frame around the body
        self.win.withdraw()

        self.body = tk.Frame(self.win, bg=T.SHELL, padx=16, pady=13)
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        self.body.columnconfigure(1, weight=1)

        self._build()
        self.win.bind("<FocusOut>", self._focus_out)
        self.win.bind("<Escape>", lambda _e: self.hide())

    # ---------------------------------------------------------------- building

    def _rule(self, row: int) -> None:
        tk.Frame(self.body, bg=T.RAIL, height=1).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=9)

    def _dim(self, text: str, row: int, col: int = 0) -> tk.Label:
        label = tk.Label(self.body, text=text, bg=T.SHELL, fg=T.INK_DIM,
                         font=T.FONT_UI, anchor="w")
        label.grid(row=row, column=col, sticky="w")
        return label

    def _build(self) -> None:
        head = tk.Frame(self.body, bg=T.SHELL)
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        head.columnconfigure(1, weight=1)

        self.dot = tk.Canvas(head, width=10, height=10, bg=T.SHELL,
                             highlightthickness=0, bd=0)
        self.dot.grid(row=0, column=0, padx=(0, 8))
        self._dot_id = self.dot.create_oval(1, 1, 9, 9, fill=T.INK_DIM, outline="")

        self.state_label = tk.Label(head, text="ready", bg=T.SHELL, fg=T.INK,
                                    font=T.FONT_UI_SEMI, anchor="w")
        self.state_label.grid(row=0, column=1, sticky="w")

        self.engine_label = tk.Label(head, text="", bg=T.SHELL, fg=T.INK_DIM,
                                     font=T.FONT_UI, anchor="e")
        self.engine_label.grid(row=0, column=2, sticky="e")

        self._rule(1)

        self._dim("Language", 2)
        segment = tk.Frame(self.body, bg=T.WELL)
        segment.grid(row=2, column=1, sticky="e")
        self.lang_buttons: dict[str, tk.Button] = {}
        # the segmented control mirrors `language_cycle` from the config
        for code in (list(self.cfg.language_cycle) or ["auto"]):
            label = code.upper()
            button = tk.Button(
                segment, text=label, font=T.FONT_UI, relief="flat", bd=0,
                padx=13, pady=3, cursor="hand2", highlightthickness=0,
                command=(lambda c=code: self._pick_language(c)),
            )
            button.pack(side="left", padx=1, pady=1)
            self.lang_buttons[code] = button

        self._dim("Engine", 3)
        self.unload_button = tk.Button(
            self.body, text="unload", command=self._unload, bg=T.SHELL,
            fg=T.INK_DIM, activebackground=T.SHELL, activeforeground=T.INK,
            font=T.FONT_UI, relief="flat", bd=0, cursor="hand2",
            highlightthickness=0, padx=0,
        )
        self.unload_button.grid(row=3, column=1, sticky="e")

        self._rule(4)

        self.toggles: dict[str, tk.Button] = {}
        rows = [
            ("overlay", "Overlay while talking"),
            ("beep", "Sound feedback"),
            ("keep_warm", "Keep the model in memory"),
        ]
        for i, (key, text) in enumerate(rows):
            self._dim(text, 5 + i)
            button = tk.Button(
                self.body, text="", command=(lambda k=key: self._toggle(k)),
                bg=T.SHELL, fg=T.INK, activebackground=T.SHELL,
                activeforeground=T.INK, font=T.FONT_UI_SEMI, relief="flat",
                bd=0, cursor="hand2", highlightthickness=0, width=6,
            )
            button.grid(row=5 + i, column=1, sticky="e", pady=1)
            self.toggles[key] = button

        self._rule(8)

        self.keys_label = tk.Label(self.body, text="", bg=T.SHELL, fg=T.INK_DIM,
                                   font=T.FONT_UI, anchor="w", justify="left")
        self.keys_label.grid(row=9, column=0, columnspan=2, sticky="w")

        bar = tk.Frame(self.body, bg=T.SHELL)
        bar.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(11, 0))
        self._link(bar, "Quit", self._quit, T.INK_DIM).pack(side="right")
        self._link(bar, "Settings", self._settings, T.AMBER).pack(
            side="right", padx=(0, 14))

    def _link(self, parent, text: str, command, fg: str) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command, bg=T.SHELL, fg=fg,
            activebackground=T.SHELL, activeforeground=T.INK, font=T.FONT_UI_SEMI,
            relief="flat", bd=0, cursor="hand2", highlightthickness=0, padx=0,
        )

    # ---------------------------------------------------------------- state

    def set_status(self, text: str, color: str) -> None:
        self._status = (text, color)
        if self.visible:
            self.state_label.configure(text=text)
            self.dot.itemconfigure(self._dot_id, fill=color)

    def refresh(self) -> None:
        text, color = self._status
        self.state_label.configure(text=text)
        self.dot.itemconfigure(self._dot_id, fill=color)
        self.engine_label.configure(text=f"engine: {self.app.engine.backend}")

        for code, button in self.lang_buttons.items():
            on = self.cfg.language == code
            button.configure(bg=T.RAIL if on else T.WELL,
                             fg=T.AMBER if on else T.INK_DIM,
                             activebackground=T.RAIL, activeforeground=T.INK)

        for key, button in self.toggles.items():
            on = bool(getattr(self.cfg, key))
            button.configure(text="on" if on else "off",
                             fg=T.AMBER if on else T.INK_DIM)

        self.keys_label.configure(
            text=f"{pretty(self.cfg.hotkey)} talk   ·   "
                 f"{pretty(self.cfg.lang_key)} language   ·   "
                 f"{pretty(self.cfg.repaste_key)} repeat"
        )

    # ---------------------------------------------------------------- actions

    def _pick_language(self, code: str) -> None:
        self.app.set_language(code)
        self.refresh()

    def _toggle(self, key: str) -> None:
        if key == "keep_warm":
            self.app.toggle_keep_warm()
        else:
            setattr(self.cfg, key, not getattr(self.cfg, key))
            self.cfg.save()
            self.app.apply_quick_setting(key)
        self.refresh()

    def _unload(self) -> None:
        self.app.unload_model()
        self.win.after(400, self.refresh)

    def _settings(self) -> None:
        self.hide()
        self.app.open_settings()

    def _quit(self) -> None:
        self.hide()
        self.app.quit()

    # ---------------------------------------------------------------- window

    def _place(self) -> None:
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        px, py = self.root.winfo_pointerxy()
        x = min(max(MARGIN, px - w // 2), sw - w - MARGIN)
        y = py - h - MARGIN
        if y < MARGIN:                      # taskbar on top: open downwards
            y = min(py + MARGIN, sh - h - MARGIN)
        y = min(y, sh - TASKBAR - h)
        self.win.geometry(f"{w}x{h}+{int(x)}+{max(MARGIN, int(y))}")

    def show(self) -> None:
        self.refresh()
        self._place()
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.win.focus_force()
        self.visible = True

    def hide(self) -> None:
        if not self.visible:
            return
        self.visible = False
        self._closed_at = time.time()
        self.win.withdraw()

    def toggle(self) -> None:
        # Clicking the tray takes focus first, so the panel hides itself; the
        # toggle that follows must not reopen it.
        if self.visible or time.time() - self._closed_at < 0.35:
            self.hide()
            return
        self.show()

    def _focus_out(self, _event) -> None:
        self.win.after(80, self._check_focus)

    def _check_focus(self) -> None:
        if not self.visible:
            return
        try:
            if self.win.focus_get() is None:
                self.hide()
        except (KeyError, tk.TclError):
            self.hide()
