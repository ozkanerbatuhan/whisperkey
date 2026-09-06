"""Clipboard and pasting.

Win32 directly instead of pyperclip: when the clipboard is locked by another
process we can retry and report the outcome instead of swallowing the error.
"""

from __future__ import annotations

import ctypes
import time

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_k32.GlobalAlloc.restype = ctypes.c_void_p
_k32.GlobalLock.restype = ctypes.c_void_p
_k32.GlobalLock.argtypes = [ctypes.c_void_p]
_k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
_u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
_u32.SetClipboardData.restype = ctypes.c_void_p
_u32.GetClipboardData.restype = ctypes.c_void_p


def _open_clipboard(tries: int = 10) -> bool:
    for _ in range(tries):
        if _u32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def get_text() -> str | None:
    if not _open_clipboard():
        return None
    try:
        handle = _u32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = _k32.GlobalLock(ctypes.c_void_p(handle))
        if not ptr:
            return None
        try:
            return ctypes.c_wchar_p(ptr).value
        finally:
            _k32.GlobalUnlock(ctypes.c_void_p(handle))
    finally:
        _u32.CloseClipboard()


def set_text(text: str) -> bool:
    buf = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(buf)
    if not _open_clipboard():
        return False
    try:
        _u32.EmptyClipboard()
        handle = _k32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        ptr = _k32.GlobalLock(ctypes.c_void_p(handle))
        ctypes.memmove(ptr, ctypes.byref(buf), size)
        _k32.GlobalUnlock(ctypes.c_void_p(handle))
        return bool(_u32.SetClipboardData(CF_UNICODETEXT, ctypes.c_void_p(handle)))
    finally:
        _u32.CloseClipboard()


def _release_modifiers(keys: tuple[str, ...] = ("ctrl", "shift", "alt", "f8", "f9", "f10")) -> None:
    """A key still held down breaks the paste (e.g. Ctrl held during Ctrl+V)."""
    import keyboard

    for key in keys:
        try:
            keyboard.release(key)
        except Exception:
            pass


def paste(text: str, paste_keys: str = "ctrl+v", restore: bool = True) -> bool:
    """Put the text on the clipboard and paste it into the focused window."""
    import keyboard

    previous = get_text() if restore else None
    if not set_text(text):
        return False
    _release_modifiers()
    time.sleep(0.05)
    keyboard.send(paste_keys)
    if previous is not None:
        time.sleep(0.35)  # restoring too early would paste the old text
        set_text(previous)
    return True


def copy_only(text: str) -> bool:
    return set_text(text)
