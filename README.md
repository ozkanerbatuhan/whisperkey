<div align="center">

# whisperkey

**Hold a key, talk, and the text lands in whatever window you are in.**

Local, offline, free. No account, no API key, nothing leaves the machine.

[![CI](https://github.com/ozkanerbatuhan/whisperkey/actions/workflows/ci.yml/badge.svg)](https://github.com/ozkanerbatuhan/whisperkey/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/platform-windows-lightgrey.svg)](#requirements)

</div>

---

Dictation tools usually want a subscription, a network round trip, or both.
whisperkey is a tray application that runs [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
on your own GPU: hold F9, speak, let go, and the transcript is pasted into the
focused window — editor, terminal, browser, chat, anything that takes text.

It handles code-switching. A sentence that mixes two languages, with English
technical terms dropped into it, is what the default prompt is tuned for.

## Why it might suit you

- **Nothing leaves the machine.** The model runs locally; there is no server.
- **Idle cost is near zero.** The engine lives in its own process: born when
  you start talking, killed after five idle minutes. The tray app itself sits
  at 61 MB.
- **It pastes, not types.** Text goes through the clipboard and Ctrl+V, and the
  previous clipboard contents are restored afterwards.
- **Everything is rebindable.** Click a shortcut field, press the key you want.
- **Small enough to read.** ~2,700 lines of Python, no framework.

## Install

Requires Python 3.10+ on Windows. An NVIDIA GPU is optional but makes it
roughly five times faster.

```bash
git clone https://github.com/ozkanerbatuhan/whisperkey
cd whisperkey

# uv (fast) ...
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt

# ... or plain pip
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# download the model once (~1.6 GB, into models/)
whisperkey.bat --warmup
```

CPU only? Drop the two `nvidia-*` lines from `requirements.txt` before
installing and set `"device": "cpu"` in the config.

Then start it with **`whisperkey-silent.bat`** — it goes to the notification
area. Windows hides new tray icons under the `^` overflow by default; drag it
onto the taskbar to keep it visible.

## Use

| key | what it does |
|---|---|
| **hold F9** | talk; releasing pastes the text into the focused window |
| **tap F9** | hands-free mode; tap F9 again to finish |
| **Esc** | cancel while recording |
| **F10** | cycle language (auto → English by default) |
| **F8** | paste the last transcript again |
| **Ctrl while pressing F9** | copy to the clipboard instead of pasting |

None of these are fixed. In **Settings → Shortcuts**, click a field and press
the key (or a combination such as Ctrl+Shift+F9) you want. Esc cancels. Because
the talk key is swallowed globally, a bare letter with no modifier is rejected —
otherwise you could never type that letter again.

**Tray icon.** Left click opens a small panel next to the cursor: status,
language, engine, the overlay/sound/keep-warm switches and a shortcut reminder.
Right click gives the full menu.

## Memory and speed

The engine lives in a separate process: it is born when you start talking and
killed after five idle minutes. Measured with large-v3-turbo on an RTX 3050 Ti:

| | RAM | VRAM |
|---|---|---|
| idle (interface only) | 61 MB | 0 MB |
| engine up | +674 MB | +2243 MB |

| operation | time |
|---|---|
| 5 s of speech, engine warm | 1.1 s |
| 5 s of speech, engine cold | ~6 s |

The engine is fired the moment recording starts, so loading overlaps with your
speech — that is why a cold start costs 6 seconds, not 12.

If you never want to wait, tick **Keep the model in memory** in the tray: the
engine never dies, every utterance takes 1.1 s, and the memory stays occupied.

## Commands

```
whisperkey.bat                    run with a console
whisperkey.bat --devices          list microphones
whisperkey.bat --warmup           download and load the model
whisperkey.bat --selftest a.wav   transcribe a file (no GUI, no microphone)
```

Installed as a package (`pip install -e .`), the same commands are available as
`whisperkey`, `whisperkey --devices`, and so on.

## Configuration

`config.json` is created on the first save and edited from **Settings** in the
tray. It lives in the repository root when you run from a checkout, in
`%LOCALAPPDATA%\whisperkey` when installed as a package, or wherever
`WHISPERKEY_HOME` points.

Worth knowing:

| key | meaning |
|---|---|
| `model` | `tiny` … `large-v3`. Default `large-v3-turbo`: the best balance of quality and speed. |
| `compute_type` | `auto` looks at free VRAM: over 3 GB free → `float16` (5.4 s load), otherwise `int8_float16` (2 GB less memory, 9.4 s load). Transcription speed is identical; only loading differs. |
| `language` | `auto` or any Whisper language code. |
| `language_cycle` | what the language key steps through, e.g. `["auto", "en", "de"]`. |
| `initial_prompt` | shows the model the speaking style to expect. It measurably improves how English technical terms are spelled inside another language. Put your own vocabulary here. |
| `idle_unload_sec` | how long the engine may sit idle before it is killed. `0` = never. |
| `paste_keys` | set to `shift+insert` where a terminal swallows Ctrl+V. |
| `sound_volume` | feedback volume (0–1). The sounds are `src/whisperkey/assets/sounds/*.wav`, generated by `tools/make_sounds.py`. |

## How it works

```
keyboard hook ──> state machine ──> recorder ──┐
   (F9)            hold vs tap      (sounddevice)
                                               │  float32 audio
                                               v
tray + overlay <── UI queue <── worker ──> engine process
   (tkinter)                                (faster-whisper, CUDA)
                                               │  text
                                               v
                                          clipboard ──> Ctrl+V
```

Four threads and one child process. Every UI call goes through a queue onto the
tkinter main thread; the worker is a single consumer, so utterances keep their
order. `states.py` is pure — it takes a timestamp and returns an action, which
is why the hold/tap/cancel behavior is testable without a GUI or a microphone.

See [docs/design.md](docs/design.md) for the reasoning, including why the
engine needs its own process and why this is Python rather than Rust.

## Tests

```bash
.venv\Scripts\python.exe -m pytest tests -q
```

The state machine (`states.py`), shortcut parsing (`hotkeys.py`) and the sound
layer (`sounds.py`) are all tested without a GUI or audio hardware.

## Requirements

- Windows 10/11 (the clipboard, tray and overlay layers are Win32)
- Python 3.10+
- NVIDIA GPU with CUDA — optional; without one it falls back to the CPU

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
The nearest open items are in [docs/ROADMAP.md](docs/ROADMAP.md); automatic
start/stop on silence is the big one.

## License

MIT — see [LICENSE](LICENSE).
