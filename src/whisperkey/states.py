"""Push-to-talk state machine.

Pure: knows nothing about audio, GUI or the keyboard library. It takes a
timestamp and returns an action, which is why it can be tested on its own.
"""

from __future__ import annotations

from enum import Enum

TAP_THRESHOLD = 0.4  # seconds - a press shorter than this counts as a "tap"


class Mode(Enum):
    IDLE = "idle"
    HOLD = "hold"       # key held down, releasing it ends the recording
    TOGGLE = "toggle"   # hands-free, pressing again ends the recording


class Action(Enum):
    NONE = "none"
    START = "start"
    STOP = "stop"
    CANCEL = "cancel"


class PttMachine:
    """Tells a hold apart from a tap on a single key."""

    def __init__(self, tap_threshold: float = TAP_THRESHOLD):
        self.tap_threshold = tap_threshold
        self.mode = Mode.IDLE
        self._down_at = 0.0

    @property
    def recording(self) -> bool:
        return self.mode is not Mode.IDLE

    def key_down(self, now: float) -> Action:
        if self.mode is Mode.IDLE:
            self._down_at = now
            self.mode = Mode.HOLD
            return Action.START
        if self.mode is Mode.TOGGLE:
            self.mode = Mode.IDLE
            return Action.STOP
        return Action.NONE  # key auto-repeat while HOLD

    def key_up(self, now: float) -> Action:
        if self.mode is not Mode.HOLD:
            return Action.NONE
        if now - self._down_at < self.tap_threshold:
            self.mode = Mode.TOGGLE
            return Action.NONE
        self.mode = Mode.IDLE
        return Action.STOP

    def voice_start(self) -> Action:
        """A spoken "start dictating": hands-free, like a tap on the key."""
        if self.mode is not Mode.IDLE:
            return Action.NONE
        self.mode = Mode.TOGGLE
        return Action.START

    def voice_stop(self) -> Action:
        if self.mode is Mode.IDLE:
            return Action.NONE
        self.mode = Mode.IDLE
        return Action.STOP

    def cancel(self) -> Action:
        if self.mode is Mode.IDLE:
            return Action.NONE
        self.mode = Mode.IDLE
        return Action.CANCEL
