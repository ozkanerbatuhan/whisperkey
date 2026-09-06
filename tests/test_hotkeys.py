import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whisperkey.hotkeys import (  # noqa: E402
    check_hotkey,
    format_hotkey,
    pretty,
    split_hotkey,
)


def test_format_orders_modifiers():
    assert format_hotkey(["shift", "ctrl", "f9"]) == "ctrl+shift+f9"
    assert format_hotkey(["f9"]) == "f9"


def test_format_normalizes_sides_and_repeats():
    assert format_hotkey(["left ctrl", "right ctrl", "a"]) == "ctrl+a"
    assert format_hotkey(["alt gr", "left shift", "space"]) == "alt+shift+space"


def test_split_returns_main_key_last():
    assert split_hotkey("ctrl+shift+f9") == (["ctrl", "shift"], "f9")
    assert split_hotkey("f9") == ([], "f9")
    assert split_hotkey("ctrl") == (["ctrl"], "")


def test_bare_letter_is_rejected():
    # the talk key is swallowed globally: a bare letter would kill typing it
    assert check_hotkey("a") is not None
    assert check_hotkey("7") is not None
    assert check_hotkey("ctrl+a") is None
    assert check_hotkey("f9") is None
    assert check_hotkey("") is not None
    assert check_hotkey("ctrl") is not None


def test_pretty_reads_like_a_shortcut():
    assert pretty("ctrl+shift+f9") == "Ctrl + Shift + F9"
    assert pretty("f9") == "F9"
    assert pretty("") == "-"
