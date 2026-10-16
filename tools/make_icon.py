"""Generates the application icon: src/whisperkey/assets/whisperkey.ico

The same drawing as the tray icon (ui/tray.py) - a dark body with three meter
bars - in the amber "working" color, drawn at 1024 px and downsampled so the
small sizes stay crisp. Also writes docs/icon.png for the README. Run it once
and commit the output:

    .venv/Scripts/python.exe tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ICO = ROOT / "src" / "whisperkey" / "assets" / "whisperkey.ico"
PNG = ROOT / "docs" / "icon.png"

# colors from ui/theme.py: SHELL, RAIL, AMBER
SHELL, RAIL, ACCENT = "#171A1F", "#2A2F37", "#FFB000"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw(size: int = 1024) -> Image.Image:
    k = size / 64  # the design is laid out on a 64 px grid, like the tray icon
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2 * k, 2 * k, size - 2 * k, size - 2 * k),
                        radius=14 * k, fill=SHELL, outline=RAIL, width=int(2 * k))
    for i, (top, bottom) in enumerate([(20, 44), (12, 52), (24, 40)]):
        x = 18 + i * 11
        d.rounded_rectangle((x * k, top * k, (x + 6) * k, bottom * k),
                            radius=3 * k, fill=ACCENT)
    return img


def main() -> None:
    big = draw().resize((256, 256), Image.LANCZOS)
    ICO.parent.mkdir(parents=True, exist_ok=True)
    big.save(ICO, sizes=[(s, s) for s in SIZES])
    big.resize((128, 128), Image.LANCZOS).save(PNG)
    print(f"wrote {ICO.relative_to(ROOT)} and {PNG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
