# Contributing

Thanks for taking a look. This is a small project — one file per concern, no
framework — so most changes stay local.

## Getting set up

```bash
git clone https://github.com/ozkanerbatuhan/whisperkey
cd whisperkey
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python.exe -m whisperkey --warmup
```

## Before opening a pull request

```bash
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\ruff check src tests tools
```

CI runs both on Windows for Python 3.10 and 3.12.

## House rules

- **Keep the tested layers dependency free.** `states.py`, `hotkeys.py` and
  `sounds.py` are testable without a GUI, a microphone or CUDA. That is what
  makes CI possible on a runner. Do not pull audio or tkinter into them.
- **Never touch the UI from another thread.** Everything goes through
  `App.post_ui`, which hands the call to the tkinter main thread.
- **Measure claims about memory and speed.** The numbers in the README came
  from a real machine; if you change the engine layer, re-measure rather than
  reasoning about it.
- **The overlay must not take focus.** If it does, Ctrl+V goes to the overlay
  instead of the target window. `ui/overlay.py` explains the Win32 flags.
- **Esc stays unsuppressed.** Swallowing it globally would lock up terminals.
- Comments explain *why*, not *what*. English, please.

## Reporting a bug

Include: Windows version, Python version, GPU (or "CPU only"), the model you
are on, and the console output from `whisperkey.bat` — the console build prints
the reason for every failure, while the overlay only flashes it.
