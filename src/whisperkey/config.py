r"""Loading and saving settings. A broken file never stops the program.

Where the data lives:
  * `WHISPERKEY_HOME` if it is set,
  * otherwise the repository root when running from a source checkout,
  * otherwise `%LOCALAPPDATA%\whisperkey` (a pip install).

`config.json` and the downloaded models both live there.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def _data_dir() -> Path:
    override = os.environ.get("WHISPERKEY_HOME")
    if override:
        return Path(override).expanduser()
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "pyproject.toml").exists():
        return checkout
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "whisperkey"


DATA_DIR = _data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
MODEL_DIR = DATA_DIR / "models"

# Shown to the model as an example of the expected speaking style. Mixing a
# second language into one sentence is exactly what Whisper gets wrong on its
# own, so the default demonstrates it; replace it with your own vocabulary.
DEFAULT_PROMPT = (
    "Today I hit a timing constraint error on the FPGA side, then committed "
    "and pushed. Let's run DRC and ERC before we merge the pull request."
)


@dataclass
class Config:
    # model
    model: str = "large-v3-turbo"
    device: str = "auto"            # auto | cuda | cpu
    compute_type: str = "auto"      # auto | int8_float16 | float16 | int8
    language: str = "auto"          # auto | any Whisper language code
    beam_size: int = 1
    vad: bool = True
    initial_prompt: str = DEFAULT_PROMPT

    # memory
    idle_unload_sec: int = 300      # 0 = never unload
    keep_warm: bool = False

    # audio
    samplerate: int = 16000
    input_device: str = ""          # empty = system default
    min_duration: float = 0.35

    # keys
    hotkey: str = "f9"
    lang_key: str = "f10"
    repaste_key: str = "f8"
    copy_modifier: str = "ctrl"     # holding this turns the hotkey into copy-only
    tap_threshold: float = 0.4

    # pasting
    paste_keys: str = "ctrl+v"      # if the terminal swallows it: shift+insert
    restore_clipboard: bool = True

    # interface
    overlay: bool = True
    overlay_offset: int = 90        # pixels above the taskbar
    beep: bool = True
    sound_volume: float = 0.7       # 0 = silent, 1 = as recorded

    # read aloud (Piper); empty tts_key turns it off
    tts_key: str = ""               # tap: play / pause, double tap: media play/pause
    tts_prev_key: str = ""          # previous / next chapter
    tts_next_key: str = ""
    tts_prev_idle: str = ""         # sent by those keys when nothing is being read,
    tts_next_idle: str = ""         # e.g. "ctrl+shift+tab" / "ctrl+tab" for a knob
    tts_voice: str = "voices/tr_TR-dfki-medium.onnx"   # relative to the data dir
    tts_source: str = "~/.claude/last-answer.txt"      # the file that is read
    tts_speed: float = 1.5
    double_tap: float = 0.35

    # voice commands (Vosk, always listening); off by default
    voice: bool = False
    voice_name: str = ""            # the wake name, asked on first start ("<name> listen")
    voice_model: str = "voices/vosk-model-small-tr-0.3"  # relative to the data dir
    voice_silence: float = 2.5      # spoken dictation ends after this much silence
    voice_phrases: dict = field(default_factory=dict)   # action -> [phrases]; empty = defaults
    # spoken dictation is typed into the console of the process named in this
    # file, in the background; empty = paste into the focused window instead
    voice_target: str = "~/.claude/last-session.json"

    # what the language key cycles through; add your own codes here
    language_cycle: list = field(default_factory=lambda: ["auto", "en"])

    _unknown: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> Config:
        cfg = cls()
        if not path.exists():
            return cfg
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[warning] could not read config.json ({exc}); using defaults")
            return cfg
        known = {f.name for f in fields(cls)}
        for key, value in raw.items():
            if key in known and not key.startswith("_"):
                setattr(cfg, key, value)
            else:
                cfg._unknown[key] = value
        return cfg

    def save(self, path: Path = CONFIG_PATH) -> None:
        data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        data.update(self._unknown)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
