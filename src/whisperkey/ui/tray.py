"""System tray icon. Runs on its own thread; menu callbacks go to the app."""

from __future__ import annotations

import threading

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

from . import theme as T

# A short list on purpose - Whisper speaks far more languages than this, and
# any code can be typed into the settings window. These are the ones worth a
# single click.
LANGS = [
    ("auto", "Auto detect"), ("en", "English"), ("es", "Spanish"),
    ("fr", "French"), ("de", "German"), ("it", "Italian"),
    ("pt", "Portuguese"), ("nl", "Dutch"), ("pl", "Polish"),
    ("ru", "Russian"), ("tr", "Turkish"), ("ar", "Arabic"),
    ("hi", "Hindi"), ("zh", "Chinese"), ("ja", "Japanese"),
    ("ko", "Korean"),
]


def _icon_image(accent: str) -> Image.Image:
    """A body plus three meter bars. The color carries the state."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, size - 4, size - 4), radius=14,
                        fill=T.SHELL, outline=T.RAIL, width=2)
    heights = [(20, 44), (14, 50), (24, 40)]
    for i, (top, bottom) in enumerate(heights):
        x = 20 + i * 10
        d.rounded_rectangle((x, top, x + 5, bottom), radius=2, fill=accent)
    return img


class Tray:
    def __init__(self, app):
        self.app = app
        self._icon = Icon("whisperkey", _icon_image(T.INK_DIM), "whisperkey",
                          menu=self._menu())
        self._thread = None

    # -- menu

    def _menu(self) -> Menu:
        return Menu(
            # default=True -> left click runs this; it stays out of the menu
            MenuItem("Panel", lambda _i, _it: self.app.toggle_panel(),
                     default=True, visible=False),
            MenuItem(lambda _: self.app.status_line(), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Language", Menu(*[
                MenuItem(
                    label,
                    # the code is bound by the outer lambda, not the loop
                    (lambda c: lambda _i, _it: self.app.set_language(c))(code),  # noqa: B023
                    checked=(lambda c: lambda _it: self.app.cfg.language == c)(code),  # noqa: B023
                    radio=True,
                )
                for code, label in LANGS
            ])),
            MenuItem(
                "Keep the model in memory",
                lambda _i, _it: self.app.toggle_keep_warm(),
                checked=lambda _it: self.app.cfg.keep_warm,
            ),
            MenuItem("Unload the model now", lambda _i, _it: self.app.unload_model()),
            Menu.SEPARATOR,
            MenuItem("Show panel", lambda _i, _it: self.app.toggle_panel()),
            MenuItem("Settings", lambda _i, _it: self.app.open_settings()),
            MenuItem("Quit", lambda _i, _it: self.app.quit()),
        )

    # -- state

    def set_accent(self, color: str) -> None:
        try:
            self._icon.icon = _icon_image(color)
        except Exception:
            pass

    def set_tooltip(self, text: str) -> None:
        try:
            self._icon.title = f"whisperkey - {text}"
        except Exception:
            pass

    def refresh(self) -> None:
        try:
            self._icon.update_menu()
        except Exception:
            pass

    def notify(self, message: str, title: str = "whisperkey") -> None:
        try:
            self._icon.notify(message, title)
        except Exception:
            pass

    # -- lifecycle

    def start(self) -> None:
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
