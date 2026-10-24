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
        self._reading = False
        self._paused = False
        self._hover = False
        # read-aloud controls, set by the app: seek(fraction), speed(+1|-1)
        self.on_seek = None
        self.on_speed = None

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

    # -- read-aloud mode: chapter strip, click to seek, − speed +

    BAR_L, BAR_R, BAR_T, BAR_B = 26, T.WIDTH - 17, 35, 45

    def _build_reading(self) -> None:
        c = self.canvas
        # the click target covers the whole meter row, a bit taller than the strip
        c.create_rectangle(self.BAR_L - 3, 30, self.BAR_R, 50, fill=T.SHELL, outline="",
                           tags=("rd", "seek"))
        x = T.WIDTH - 18
        self._plus = c.create_text(x, 19, anchor="e", text="+", fill=T.INK,
                                   font=T.FONT_UI_SEMI, tags=("rd", "plus"))
        self._speed = c.create_text(x - 16, 19, anchor="e", text="1.5x", fill=T.INK_DIM,
                                    font=self._mono(), tags=("rd",))
        self._minus = c.create_text(x - 52, 19, anchor="e", text="−", fill=T.INK,
                                    font=T.FONT_UI_SEMI, tags=("rd", "minus"))
        # generous hit boxes: the glyphs themselves are a few pixels wide
        for tag, cx in (("plus", x - 4), ("minus", x - 56)):
            c.create_rectangle(cx - 9, 6, cx + 9, 30, fill="", outline="", tags=("rd", tag))
        c.tag_bind("seek", "<Button-1>", self._click_seek)
        c.tag_bind("plus", "<Button-1>", lambda e: self.on_speed and self.on_speed(+1))
        c.tag_bind("minus", "<Button-1>", lambda e: self.on_speed and self.on_speed(-1))
        c.bind("<Enter>", self._enter)
        c.bind("<Leave>", self._leave)
        c.itemconfigure("rd", state="hidden")

    def _click_seek(self, event) -> None:
        if self.on_seek:
            self.on_seek(max(0.0, min(1.0, (event.x - self.BAR_L) / (self.BAR_R - self.BAR_L))))

    def _enter(self, _event) -> None:
        # pointer on the bar: do not vanish under the mouse
        self._hover = True
        if self._hide_job is not None:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None

    def _leave(self, _event) -> None:
        self._hover = False
        if self._reading and self._paused:
            self._hide_job = self.root.after(2500, self.hide)

    def show_reading(self, label: str, fraction: float, chapters, speed: float,
                     playing: bool, hide_after: int | None = None) -> None:
        """chapters: [(start, end, title)] as fractions; drawn as separate segments."""
        c = self.canvas
        if not self._reading:
            self._stop_scan()
            self._reading = True
            if not hasattr(self, "_plus"):
                self._build_reading()
            for item in self.ticks:
                c.itemconfigure(item, state="hidden")
            c.itemconfigure(self.peak_mark, state="hidden")
            c.itemconfigure(self.lang, state="hidden")
            c.itemconfigure("rd", state="normal")
        self._paused = not playing
        color = T.DONE if playing else T.INK_DIM
        c.itemconfigure(self.label, text=label)
        c.itemconfigure(self.stripe, fill=color)
        c.itemconfigure(self._speed, text=f"{speed:.1f}x")

        c.delete("seg")
        width = self.BAR_R - self.BAR_L
        gap = 3 if len(chapters) > 1 else 0
        for start, end, _title in chapters:
            x1 = self.BAR_L + start * width
            x2 = max(x1 + 2, self.BAR_L + end * width - gap)
            c.create_rectangle(x1, self.BAR_T, x2, self.BAR_B, fill=T.IDLE_TICK,
                               outline="", tags=("seg",))
            done = min(x2, self.BAR_L + fraction * width)
            if done > x1:
                c.create_rectangle(x1, self.BAR_T, done, self.BAR_B, fill=color,
                                   outline="", tags=("seg",))
        head = self.BAR_L + fraction * width
        c.create_rectangle(head - 1, self.BAR_T - 3, head + 1, self.BAR_B + 3,
                           fill="#FFFFFF", outline="", tags=("seg",))
        # clicks land on the strip too, not only on the background
        c.tag_bind("seg", "<Button-1>", self._click_seek)

        if not self._visible:
            self._place()
            self._apply_exstyle()
            _u32.ShowWindow(ctypes.c_void_p(self._hwnd), SW_SHOWNOACTIVATE)
            self._visible = True
        if self._hide_job is not None:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if hide_after and not self._hover:
            self._hide_job = self.root.after(hide_after, self.hide)

    def _end_reading(self) -> None:
        if not self._reading:
            return
        self._reading = False
        c = self.canvas
        c.delete("seg")
        c.itemconfigure("rd", state="hidden")
        c.itemconfigure(self.lang, state="normal")
        for item in self.ticks:
            c.itemconfigure(item, state="normal")

    @property
    def reading(self) -> bool:
        return self._reading

    def set_language(self, lang: str) -> None:
        self.canvas.itemconfigure(self.lang, text=lang)

    def show(self, text: str, color: str, hide_after: int | None = None,
             busy: bool = False) -> None:
        if self._hide_job is not None:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        self._end_reading()
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
        self._end_reading()
