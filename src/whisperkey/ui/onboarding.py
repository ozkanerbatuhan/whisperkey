"""First start of voice commands: pick a wake name, then see the commands.

There is no built-in wake word. Every command that could fire by accident
starts with a name the user chooses ("<name> listen"), so it is asked for once,
the first time voice commands are turned on. The command list can be opened
again later from the tray panel.
"""

from __future__ import annotations

import tkinter as tk

from . import theme as T

ACTION_TEXT = [
    ("dictate", "start dictating", "always"),
    ("done", "finish - type the text", "while dictating"),
    ("send", "finish and press Enter", "while dictating, or up to 15 s after"),
    ("cancel", "throw the recording away", "while dictating"),
    ("read", "read the last answer aloud", "always"),
    ("pause", "pause", "while reading"),
    ("resume", "resume", "while reading"),
    ("next", "next chapter", "while reading"),
    ("prev", "previous chapter", "while reading"),
    ("close", "close the AI session (types /exit)", "always"),
]


class _Dialog:
    def __init__(self, root: tk.Tk, title: str):
        self.win = tk.Toplevel(root)
        self.win.title(title)
        self.win.configure(bg=T.SHELL)
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.body = tk.Frame(self.win, bg=T.SHELL, padx=24, pady=20)
        self.body.pack(fill="both", expand=True)

    def _text(self, text: str, fg=T.INK, font=T.FONT_UI, **grid) -> tk.Label:
        label = tk.Label(self.body, text=text, bg=T.SHELL, fg=fg, font=font,
                         anchor="w", justify="left", wraplength=440)
        label.grid(sticky="w", **grid)
        return label

    def _button(self, parent, text: str, command, fg=T.AMBER) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=T.WELL, fg=fg,
                         activebackground=T.RAIL, activeforeground=T.INK,
                         font=T.FONT_UI_SEMI, relief="flat", bd=0, padx=18, pady=6,
                         cursor="hand2")

    def _show(self) -> None:
        self.win.update_idletasks()
        w, h = self.win.winfo_width(), self.win.winfo_height()
        x = (self.win.winfo_screenwidth() - w) // 2
        y = (self.win.winfo_screenheight() - h) // 3
        self.win.geometry(f"+{x}+{y}")
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()


class NameDialog(_Dialog):
    """Ask for the wake name. on_done(name) - or on_done(None) if cancelled."""

    def __init__(self, root: tk.Tk, on_done, example: str = "listen"):
        super().__init__(root, "whisperkey - voice commands")
        self.on_done = on_done
        self._text("What should I answer to?", font=T.FONT_UI_SEMI, pady=(0, 8))
        self._text(f"Every command starts with this name, like \"<name> {example}\". "
                   "A short, common word of your language works best - the speech "
                   "model only knows words from its vocabulary. Avoid one you say "
                   "all the time.", fg=T.INK_DIM, pady=(0, 12))
        self.var = tk.StringVar()
        entry = tk.Entry(self.body, textvariable=self.var, width=28, bg=T.WELL, fg=T.INK,
                         insertbackground=T.INK, relief="flat", highlightthickness=1,
                         highlightbackground=T.RAIL, highlightcolor=T.AMBER,
                         font=T.FONT_UI_SEMI)
        entry.grid(sticky="ew", pady=(0, 6), ipady=4)
        self.note = self._text("", fg=T.FAIL)
        bar = tk.Frame(self.body, bg=T.SHELL)
        bar.grid(sticky="e", pady=(10, 0))
        self._button(bar, "Cancel", self._cancel, T.INK_DIM).pack(side="right", padx=(8, 0))
        self._button(bar, "Continue", self._ok).pack(side="right")
        entry.bind("<Return>", lambda e: self._ok())
        self.win.bind("<Escape>", lambda e: self._cancel())
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)
        self._show()
        entry.focus_set()

    def _ok(self) -> None:
        name = " ".join(self.var.get().split())
        if not name or len(name.split()) > 2:
            self.note.configure(text="One word (two at most), please.")
            return
        self.win.destroy()
        self.on_done(name)

    def _cancel(self) -> None:
        self.win.destroy()
        self.on_done(None)


class CommandsDialog(_Dialog):
    """The phrases currently listened for. on_close() when dismissed."""

    def __init__(self, root: tk.Tk, table: dict[str, list[str]], on_close=None,
                 first: bool = False):
        super().__init__(root, "whisperkey - voice commands")
        self.on_close = on_close
        self._text("Voice commands are on" if first else "Voice commands",
                   font=T.FONT_UI_SEMI, pady=(0, 10))
        grid = tk.Frame(self.body, bg=T.SHELL)
        grid.grid(sticky="w")
        for row, (action, text, when) in enumerate(ACTION_TEXT):
            said = "  ·  ".join(f"\"{p}\"" for p in table.get(action, [])) or "-"
            tk.Label(grid, text=said, bg=T.SHELL, fg=T.AMBER, font=T.FONT_UI_SEMI,
                     anchor="w").grid(row=row, column=0, sticky="w", pady=2, padx=(0, 18))
            tk.Label(grid, text=text, bg=T.SHELL, fg=T.INK, font=T.FONT_UI,
                     anchor="w").grid(row=row, column=1, sticky="w", padx=(0, 18))
            tk.Label(grid, text=when, bg=T.SHELL, fg=T.INK_DIM, font=T.FONT_UI,
                     anchor="w").grid(row=row, column=2, sticky="w")
        self._text("2.5 s of silence also finishes a dictation. The text is typed into "
                   "the AI session that answered last, in the background. Change any "
                   "phrase in Settings → Voice commands; this list is in the tray panel.",
                   fg=T.INK_DIM, pady=(14, 0))
        bar = tk.Frame(self.body, bg=T.SHELL)
        bar.grid(sticky="e", pady=(14, 0))
        self._button(bar, "Start listening" if first else "Close", self._close).pack()
        self.win.bind("<Escape>", lambda e: self._close())
        self.win.bind("<Return>", lambda e: self._close())
        self.win.protocol("WM_DELETE_WINDOW", self._close)
        self._show()

    def _close(self) -> None:
        self.win.destroy()
        if self.on_close:
            self.on_close()
