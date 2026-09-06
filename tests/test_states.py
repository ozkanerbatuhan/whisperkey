import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whisperkey.states import Action, Mode, PttMachine  # noqa: E402


def test_hold_start_stop():
    m = PttMachine()
    assert m.key_down(0.0) is Action.START
    assert m.mode is Mode.HOLD
    assert m.key_up(1.0) is Action.STOP
    assert m.mode is Mode.IDLE
    assert not m.recording


def test_tap_enters_toggle():
    m = PttMachine()
    m.key_down(0.0)
    assert m.key_up(0.1) is Action.NONE
    assert m.mode is Mode.TOGGLE
    assert m.recording


def test_toggle_stops_on_next_down():
    m = PttMachine()
    m.key_down(0.0)
    m.key_up(0.1)
    assert m.key_down(5.0) is Action.STOP
    assert m.mode is Mode.IDLE


def test_toggle_ignores_key_up():
    m = PttMachine()
    m.key_down(0.0)
    m.key_up(0.1)
    assert m.key_up(0.2) is Action.NONE
    assert m.mode is Mode.TOGGLE


def test_autorepeat_does_not_restart():
    m = PttMachine()
    m.key_down(0.0)
    assert m.key_down(0.05) is Action.NONE
    assert m.mode is Mode.HOLD


def test_cancel_from_both_recording_modes():
    m = PttMachine()
    m.key_down(0.0)
    assert m.cancel() is Action.CANCEL
    assert m.mode is Mode.IDLE

    m.key_down(0.0)
    m.key_up(0.1)
    assert m.mode is Mode.TOGGLE
    assert m.cancel() is Action.CANCEL
    assert m.mode is Mode.IDLE


def test_cancel_when_idle_is_noop():
    assert PttMachine().cancel() is Action.NONE


def test_key_up_when_idle_is_noop():
    m = PttMachine()
    assert m.key_up(1.0) is Action.NONE
    assert m.mode is Mode.IDLE


def test_threshold_boundary_is_hold():
    m = PttMachine(tap_threshold=0.4)
    m.key_down(0.0)
    assert m.key_up(0.4) is Action.STOP  # exactly at the threshold counts as a hold


def test_second_cycle_after_toggle_stop():
    m = PttMachine()
    m.key_down(0.0)
    m.key_up(0.1)
    m.key_down(2.0)  # ends the toggle
    assert m.key_down(3.0) is Action.START
    assert m.mode is Mode.HOLD
