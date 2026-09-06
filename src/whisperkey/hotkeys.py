"""Global shortcuts and key capture.

Callbacks run on the `keyboard` library's hook thread - they must stay short;
anything heavy is pushed onto the app's queue.
"""

from __future__ import annotations

import threading

import keyboard

# Modifiers are always written in this order in a combination; the keyboard
# library expects the "ctrl+shift+f9" form and will not match an inconsistent one.
MODIFIERS = ("ctrl", "alt", "shift", "windows")

# captured name -> the name the library expects (left/right does not matter here)
ALIASES = {
    "left ctrl": "ctrl", "right ctrl": "ctrl",
    "left alt": "alt", "right alt": "alt", "alt gr": "alt",
    "left shift": "shift", "right shift": "shift",
    "left windows": "windows", "right windows": "windows",
}


def format_hotkey(names) -> str:
    """Turn pressed key names into a single shortcut string.

    Modifiers move to the front in a fixed order, duplicates are dropped and
    the main key stays last: ('shift', 'ctrl', 'f9') -> 'ctrl+shift+f9'.
    """
    seen: list[str] = []
    for raw in names:
        name = ALIASES.get(raw, raw)
        if name and name not in seen:
            seen.append(name)
    mods = [m for m in MODIFIERS if m in seen]
    rest = [n for n in seen if n not in MODIFIERS]
    return "+".join(mods + rest)


def split_hotkey(hotkey: str) -> tuple[list[str], str]:
    """'ctrl+shift+f9' -> (['ctrl', 'shift'], 'f9'). Empty if there is no main key."""
    parts = [p.strip().lower() for p in (hotkey or "").split("+") if p.strip()]
    mods = [p for p in parts if p in MODIFIERS]
    rest = [p for p in parts if p not in MODIFIERS]
    return mods, (rest[-1] if rest else "")


def check_hotkey(hotkey: str) -> str | None:
    """Is the shortcut safe? If not, return the reason.

    The talk key is **suppressed** globally - picking a bare letter with no
    modifier would mean that letter can never be typed anywhere again. Hence
    the rule.
    """
    mods, main = split_hotkey(hotkey)
    if not main:
        return "no main key"
    if not mods and len(main) == 1 and main.isalnum():
        return f"'{main}' alone will not do - it gets swallowed while typing, add a modifier"
    return None


def pretty(hotkey: str) -> str:
    """For display: 'ctrl+shift+f9' -> 'Ctrl + Shift + F9'."""
    if not hotkey:
        return "-"
    parts = []
    for part in hotkey.split("+"):
        part = part.strip()
        parts.append(part.upper() if len(part) <= 3 else part.capitalize())
    return " + ".join(parts)


class KeyCapture:
    """Reads the next key press and returns it as a shortcut string.

    Not `keyboard.read_hotkey`: that one does not return until a key is
    pressed and cannot be cancelled - closing the window would leave the hook
    dangling. Here `cancel()` removes the hook.
    """

    def __init__(self):
        self._hook = None
        self._done = None
        self._pressed: list[str] = []
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._hook is not None

    def start(self, on_done) -> None:
        """on_done(hotkey|None) - called on the hook thread, keep it short."""
        self.cancel()
        with self._lock:
            self._done = on_done
            self._pressed = []
            try:
                self._hook = keyboard.hook(self._handle, suppress=True)
            except Exception as exc:
                self._hook = None
                self._done = None
                print(f"[warning] could not capture the key: {exc}")
                on_done(None)

    def cancel(self) -> None:
        self._finish(None)

    def _handle(self, event) -> None:
        name = ALIASES.get(event.name or "", event.name or "")
        if not name:
            return
        if event.event_type == "down":
            if name not in self._pressed:
                self._pressed.append(name)
            return
        # release: a lone modifier is not a shortcut, wait for a main key
        combo = [n for n in self._pressed if n not in MODIFIERS]
        if not combo:
            if name in self._pressed:
                self._pressed.remove(name)
            return
        self._finish(format_hotkey(self._pressed))

    def _finish(self, value: str | None) -> None:
        with self._lock:
            hook, done = self._hook, self._done
            self._hook = self._done = None
            self._pressed = []
        if hook is not None:
            try:
                keyboard.unhook(hook)
            except Exception:
                pass
        if done is not None:
            done(value)


class Hotkeys:
    def __init__(self, cfg, on_down, on_up, on_cancel, on_lang, on_repaste):
        self.cfg = cfg
        self._on_down = on_down
        self._on_up = on_up
        self._on_cancel = on_cancel
        self._on_lang = on_lang
        self._on_repaste = on_repaste
        self._bound = False

    @staticmethod
    def ctrl_held() -> bool:
        """Ctrl held while talking = copy to the clipboard instead of pasting."""
        try:
            return keyboard.is_pressed("ctrl")
        except Exception:
            return False

    def mods_held(self) -> bool:
        """Are the talk key's modifiers currently held down."""
        mods, _ = split_hotkey(self.cfg.hotkey)
        try:
            return all(keyboard.is_pressed(m) for m in mods)
        except Exception:
            return not mods

    def bind(self) -> None:
        if self._bound:
            return
        # The talk key needs both press and release; add_hotkey gives only one
        # of them. So the main key gets a hook and modifiers are checked by hand.
        mods, main = split_hotkey(self.cfg.hotkey)
        keyboard.on_press_key(main, self._down_guard, suppress=True)
        keyboard.on_release_key(main, lambda e: self._on_up(), suppress=True)
        keyboard.add_hotkey(self.cfg.lang_key, self._on_lang, suppress=True)
        keyboard.add_hotkey(self.cfg.repaste_key, self._on_repaste, suppress=True)
        # Esc is deliberately NOT suppressed: swallowing it globally would
        # lock up terminals and editors.
        keyboard.on_press_key("esc", lambda e: self._on_cancel(), suppress=False)
        self._bound = True

    def _down_guard(self, _event) -> None:
        if self.mods_held():
            self._on_down()

    def unbind(self) -> None:
        if not self._bound:
            return
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self._bound = False
