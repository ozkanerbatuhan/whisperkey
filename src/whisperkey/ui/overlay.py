"""The recording overlay - frameless, never steals focus, hidden when idle.

Focus is the critical part: if the overlay takes focus, Ctrl+V goes to the
overlay instead of the target window. So the window is marked
WS_EX_NOACTIVATE and shown with SW_SHOWNOACTIVATE - tkinter's deiconify can
steal focus.
"""

from __future__ import annotations

import ctypes
import tkinter as tk
import tkinter.font as tkfont

from . import theme as T

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4

_u32 = ctypes.windll.user32
_get_long = getattr(_u32, "GetWindowLongPtrW", _u32.GetWindowLongW)
_set_long = getattr(_u32, "SetWindowLongPtrW", _u32.SetWindowLongW)
_get_long.restype = ctypes.c_ssize_t
_set_long.restype = ctypes.c_ssize_t
_set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]


def _round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class Overlay:
    """State plus a live level meter. Call it from the tkinter main thread only."""

    def __init__(self, root: tk.Tk, offset: int = 90):
        self.root = root
        self.offset = offset
        self._visible = False
        self._peak = 0.0
        self._hide_job = None
        self._scan_job = None
        self._scan_pos = 0

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.configure(bg=T.KEY)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", T.KEY)
        self.win.withdraw()

        self.canvas = tk.Canvas(
            self.win, width=T.WIDTH, height=T.HEIGHT,
            bg=T.KEY, highlightthickness=0, bd=0,
        )
        self.canvas.pack()
        self._build()
        self._place()
        self.root.after(30, self._apply_exstyle)

    # -- window behavior

    @property
    def _hwnd(self):
        self.win.update_idletasks()
        wid = self.win.winfo_id()
        parent = _u32.GetParent(wid)
        return parent or wid

    def _apply_exstyle(self) -> None:
        hwnd = ctypes.c_void_p(self._hwnd)
        style = _get_long(hwnd, GWL_EXSTYLE)
        _set_long(hwnd, GWL_EXSTYLE,
                  style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)

    def _place(self) -> None:
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = (sw - T.WIDTH) // 2
        y = sh - T.HEIGHT - self.offset
        self.win.geometry(f"{T.WIDTH}x{T.HEIGHT}+{x}+{y}")

    # -- drawing

    def _mono(self):
        families = set(tkfont.families(self.root))
        return T.FONT_MONO if T.FONT_MONO[0] in families else T.FONT_MONO_FALLBACK

    def _build(self) -> None:
        c = self.canvas
        _round_rect(c, 1, 1, T.WIDTH - 1, T.HEIGHT - 1, T.RADIUS,
                    fill=T.SHELL, outline=T.RAIL)

        # the left-edge stripe: its color is the state
        self.stripe = _round_rect(c, 11, 15, 15, T.HEIGHT - 15, 2,
                                  fill=T.LIVE, outline="")

        self.label = c.create_text(27, 19, anchor="w", text="",
                                   fill=T.INK, font=T.FONT_UI_SEMI)
        self.lang = c.create_text(T.WIDTH - 18, 19, anchor="e", text="auto",
                                  fill=T.INK_DIM, font=self._mono())

        # meter well and ticks
        left, right = 26, T.WIDTH - 17
        c.create_rectangle(left - 3, 33, right, 47, fill=T.WELL, outline="")
        self.ticks = []
        step = (right - left - 3) / T.TICKS
        for i in range(T.TICKS):
            x = left + i * step
            self.ticks.append(
                c.create_rectangle(x, 36, x + max(2.0, step - 2.4), 44,
                                   fill=T.IDLE_TICK, outline="")
            )
        self.peak_mark = c.create_rectangle(0, 0, 0, 0, fill="#FFFFFF", outline="")

    def _paint_meter(self, level: float) -> None:
        lit = int(level * T.TICKS)
        for i, item in enumerate(self.ticks):
            if i >= lit:
                color = T.IDLE_TICK
            elif i >= T.TICKS - T.CLIP_ZONE:
                color = T.LIVE          # clipping zone: the signal is too hot
            else:
                color = T.AMBER
            self.canvas.itemconfigure(item, fill=color)

        self._peak = max(level, self._peak - 0.02)
        idx = min(T.TICKS - 1, int(self._peak * T.TICKS))
        if self._peak > 0.02:
            x1, _, x2, _ = self.canvas.coords(self.ticks[idx])
            self.canvas.coords(self.peak_mark, x1, 33.5, x2, 36)
            self.canvas.itemconfigure(self.peak_mark, state="normal")
        else:
            self.canvas.itemconfigure(self.peak_mark, state="hidden")

    def _clear_meter(self) -> None:
        self._peak = 0.0
        for item in self.ticks:
            self.canvas.itemconfigure(item, fill=T.IDLE_TICK)
        self.canvas.itemconfigure(self.peak_mark, state="hidden")

    # -- waiting scan

    def _scan_step(self) -> None:
        span = T.TICKS + 6
        for i, item in enumerate(self.ticks):
            offset = (i - self._scan_pos) % span
            self.canvas.itemconfigure(
                item, fill=T.AMBER if offset < 4 else T.IDLE_TICK
            )
        self._scan_pos = (self._scan_pos + 1) % span
        self._scan_job = self.root.after(45, self._scan_step)

    def _start_scan(self) -> None:
        if self._scan_job is not None:
            return
        self._scan_pos = 0
        self.canvas.itemconfigure(self.peak_mark, state="hidden")
        self._scan_step()

    def _stop_scan(self) -> None:
        if self._scan_job is not None:
            self.root.after_cancel(self._scan_job)
            self._scan_job = None
        self._clear_meter()

    # -- public interface

    def set_level(self, level: float) -> None:
        if self._visible and self._scan_job is None:
            self._paint_meter(max(0.0, min(1.0, level)))

    def set_language(self, lang: str) -> None:
        self.canvas.itemconfigure(self.lang, text=lang)

    def show(self, text: str, color: str, hide_after: int | None = None,
             busy: bool = False) -> None:
        if self._hide_job is not None:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if busy:
            self._start_scan()
        else:
            self._stop_scan()
        self.canvas.itemconfigure(self.label, text=text)
        self.canvas.itemconfigure(self.stripe, fill=color)
        if not self._visible:
            self._place()
            self._apply_exstyle()
            _u32.ShowWindow(ctypes.c_void_p(self._hwnd), SW_SHOWNOACTIVATE)
            self._visible = True
        if hide_after:
            self._hide_job = self.root.after(hide_after, self.hide)

    def hide(self) -> None:
        if self._hide_job is not None:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if self._visible:
            _u32.ShowWindow(ctypes.c_void_p(self._hwnd), SW_HIDE)
            self._visible = False
        self._stop_scan()
