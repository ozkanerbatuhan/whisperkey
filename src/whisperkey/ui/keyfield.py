"""Shortcut field: click it, press a key, it is assigned. No typing "f9"."""

from __future__ import annotations

import tkinter as tk

from ..hotkeys import pretty
from . import theme as T

PROMPT = "press a key...   (Esc cancels)"


class KeyField(tk.Frame):
    """A one-line field whose value is taken from a key press.

    The application's global hooks are removed while capturing - otherwise
    pressing F9 would also start a recording. Unhooking and rebinding is the
    job of the `on_request` owner.
    """

    def __init__(self, parent, value: str, on_request, on_cancel):
        super().__init__(parent, bg=T.SHELL)
        self.value = value
        self._on_request = on_request
        self._on_cancel = on_cancel
        self.capturing = False

        self.button = tk.Button(
            self, text=pretty(value), command=self._clicked,
            bg=T.WELL, fg=T.INK, activebackground=T.RAIL, activeforeground=T.INK,
            font=T.FONT_UI_SEMI, relief="flat", bd=0, padx=12, pady=5,
            cursor="hand2", anchor="center", highlightthickness=1,
            highlightbackground=T.RAIL, highlightcolor=T.RAIL, width=18,
        )
        self.button.pack(fill="x")

    # -- public

    def get(self) -> str:
        return self.value

    def _clicked(self) -> None:
        if self.capturing:
            self._on_cancel()
        else:
            self._on_request(self)

    def set_capturing(self, on: bool) -> None:
        self.capturing = on
        if on:
            self.button.configure(text=PROMPT, fg=T.AMBER,
                                  highlightbackground=T.AMBER)
        else:
            self.button.configure(text=pretty(self.value), fg=T.INK,
                                  highlightbackground=T.RAIL)

    def apply(self, value: str | None) -> None:
        """Capture finished. None = cancelled, the old value stays."""
        if value:
            self.value = value
        self.set_capturing(False)
