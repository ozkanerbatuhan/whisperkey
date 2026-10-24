"""Type into another program's console without touching focus.

Hands-free dictation should land in the AI session that asked for it, even
while you work in another window. Windows lets a process attach to another
console and write key events straight into its input queue
(`WriteConsoleInputW`) - the window is not activated, the real keyboard and
mouse are not involved. It works for classic consoles and for Windows
Terminal tabs (ConPTY) alike.

The target's process id comes from a small JSON file that the assistant's
hook writes after every answer (see `tools/save_last_answer.py`).
"""

from __future__ import annotations

import ctypes
import json
import threading
import time
from ctypes import wintypes as w
from pathlib import Path

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = w.HANDLE
_lock = threading.Lock()                # AttachConsole is per process

KEY_EVENT = 1
VK_RETURN = 0x0D
GENERIC_RW = 0xC0000000
OPEN_EXISTING = 3


class _KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [("bKeyDown", w.BOOL), ("wRepeatCount", w.WORD), ("wVirtualKeyCode", w.WORD),
                ("wVirtualScanCode", w.WORD), ("UnicodeChar", w.WCHAR),
                ("dwControlKeyState", w.DWORD)]


class _EVENT(ctypes.Union):
    _fields_ = [("KeyEvent", _KEY_EVENT_RECORD), ("pad", ctypes.c_byte * 16)]


class _INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", w.WORD), ("Event", _EVENT)]


def _records(text: str, enter: bool):
    keys = [(0, ch) for ch in text]
    if enter:
        keys.append((VK_RETURN, "\r"))
    out = []
    for vk, ch in keys:
        for down in (True, False):
            rec = _INPUT_RECORD()
            rec.EventType = KEY_EVENT
            rec.Event.KeyEvent = _KEY_EVENT_RECORD(down, 1, vk, 0, ch, 0)
            out.append(rec)
    return out


def type_into(pid: int, text: str, enter: bool = False) -> bool:
    """Write `text` (and optionally Enter) into the console of process `pid`."""
    # one line: a newline would submit half the message in a chat prompt
    text = " ".join(text.split())
    recs = _records(text, enter)
    if not recs:
        return False
    with _lock:
        _k32.FreeConsole()
        if not _k32.AttachConsole(pid):
            return False
        try:
            handle = _k32.CreateFileW("CONIN$", GENERIC_RW, 3, None, OPEN_EXISTING, 0, None)
            if not handle or handle == w.HANDLE(-1).value:
                return False
            try:
                arr = (_INPUT_RECORD * len(recs))(*recs)
                written = w.DWORD()
                ok = _k32.WriteConsoleInputW(handle, arr, len(recs), ctypes.byref(written))
                return bool(ok) and written.value == len(recs)
            finally:
                _k32.CloseHandle(handle)
        finally:
            _k32.FreeConsole()


def target(path: str, max_age: float = 12 * 3600) -> int | None:
    """Process id of the last session that answered, if it is recent and alive."""
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        pid = int(data["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if time.time() - float(data.get("time", 0)) > max_age:
        return None
    return pid if _alive(pid) else None


def _alive(pid: int) -> bool:
    handle = _k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = w.DWORD()
        _k32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259                    # STILL_ACTIVE
    finally:
        _k32.CloseHandle(handle)
