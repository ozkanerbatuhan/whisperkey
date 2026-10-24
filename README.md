<div align="center">

<img src="docs/icon.png" width="96" alt="whisperkey icon">

# whisperkey

**Hold a key, talk, and the text lands in whatever window you are in.**
**Tap another, and it reads text back to you.**

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

It also works the other way round: a key reads a text file aloud with a local
[Piper](https://github.com/OHF-Voice/piper1-gpl) voice — for example the last
answer of an AI assistant — with chapters, seeking and live speed control in
the same overlay. See [Read aloud](#read-aloud).

And hands-free: with [voice commands](#voice-commands) on, a small offline
model listens for a few phrases, so "start dictating", "send", "read",
"next" work without touching a key — with the speaker's own voice removed
from the microphone by an echo canceller.

## Why it might suit you

- **Nothing leaves the machine.** The model runs locally; there is no server.
- **Idle cost is near zero.** The engine lives in its own process: born when
  you start talking, killed after five idle minutes. The tray app itself sits
  at 61 MB.
- **It pastes, not types.** Text goes through the clipboard and Ctrl+V, and the
  previous clipboard contents are restored afterwards.
- **Everything is rebindable.** Click a shortcut field, press the key you want.
- **Small enough to read.** ~3,400 lines of Python, no framework.

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

For a desktop shortcut with the icon (add `-StartMenu` for the Start menu too):

```bash
powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
```

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

## Read aloud

<img src="docs/reading-bar.png" width="440" alt="the reading bar: chapter title, time, speed controls and a strip split into chapters">

Off by default. Give it a key and a file, and that key reads the file aloud:

| action | what it does |
|---|---|
| **tap the read key** | start reading; tap again to pause, again to resume |
| **double tap** | media play/pause — the same key still controls your music |
| **click the strip** | jump to that point |
| **− / +** on the bar | slower / faster (0.8x–2.5x, remembered) |
| **previous / next key** | previous / next chapter |

- **Chapters.** Markdown headings and paragraphs that open with a bold label
  (`**Result:** ...`) become chapters, drawn as separate segments like the
  chapters of a video; the current one's title is on the bar. Text without
  either is split per paragraph.
- **What is read.** Code blocks, tables, links and markup are dropped; the
  rest is read sentence by sentence.
- **Fresh text wins.** If the file changed since the last reading, the next
  tap starts the new text from the top. Starting a dictation pauses the
  reading.
- **Speed.** Piper renders the first sentence in about 0.1 s once the voice is
  warm (warm-up happens at startup), so a tap starts speaking almost at once.
  It runs on the CPU and needs no GPU.

**Setup.** Install Piper and download a voice (~60 MB) into `voices/`:

```bash
uv pip install --python .venv/Scripts/python.exe piper-tts
mkdir voices
curl -L -o voices/tr_TR-dfki-medium.onnx      https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx
curl -L -o voices/tr_TR-dfki-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx.json
```

Any voice from [piper-voices](https://huggingface.co/rhasspy/piper-voices)
works — pick your language and point `tts_voice` at it. Then set the keys in
`config.json`:

```json
"tts_key": "f17",
"tts_prev_key": "f18",
"tts_next_key": "f19",
"tts_voice": "voices/tr_TR-dfki-medium.onnx",
"tts_source": "~/.claude/last-answer.txt",
"tts_speed": 1.5
```

F13–F24 are a good fit for a macro pad or a knob: no regular keyboard sends
them, so nothing else is swallowed.

**Reading an AI assistant's answers.** `tools/save_last_answer.py` is a
[Claude Code](https://docs.claude.com/en/docs/claude-code) Stop hook that writes
the last answer to `~/.claude/last-answer.txt` after every reply (headless
`claude -p` runs are skipped). Add it to `~/.claude/settings.json`:

```json
"hooks": {
  "Stop": [{ "hooks": [{ "type": "command",
    "command": "python C:\\path\\to\\whisperkey\\tools\\save_last_answer.py" }] }]
}
```

Any other tool works the same way: whatever writes the file, the key reads it.

## Voice commands

Off by default. Turn on **Voice commands** in the tray panel or Settings, and
a small [Vosk](https://alphacephei.com/vosk/) model listens for a handful of
phrases. Nothing else is transcribed or kept; Whisper only starts when you ask
it to.

There is no built-in wake word. The first time voice commands are turned on,
whisperkey asks for a **name** to answer to, then shows the command list (also
in the tray panel later). Every command that could fire by accident starts
with that name. Phrase templates exist for Turkish and English and follow the
Vosk model's language; every phrase can be changed in **Settings → Voice
commands** (several per command, separated by commas).

| command | Turkish | English | what it does |
|---|---|---|---|
| start dictating | `<name> dinle` | `<name> listen` | hands-free dictation starts (reading pauses) |
| finish | `<name> tamam` | `<name> done` | deliver the text; the phrase itself is cut from it |
| finish and send | `<name> gönder` | `<name> send` | deliver and press Enter — also up to 15 s after a dictation ended on silence |
| cancel | `<name> iptal` | `<name> cancel` | throw the recording away |
| — | 2.5 s of silence | | also finishes a spoken dictation |
| start reading | `<name> oku` | `<name> read` | read the file aloud |
| pause / resume | `dur` · `devam` | `stop` · `resume` | while reading |
| next / previous | `sonraki` · `önceki` | `next` · `previous` | jump between chapters while reading |
| close the session | `<name> kapat` | `<name> close` | types `/exit` into the AI session that answered last |

Reading commands are only listened for while something is being read, so
"next" in an everyday sentence does nothing. The name has to be a word the
speech model knows — a short, common word of your language works best.

**Where the text goes - without touching your focus.** A spoken dictation is
not pasted into the window in front: you may be busy somewhere else. It is
typed straight into the console of the AI session that answered last, in the
background (`WriteConsoleInputW` - works in Windows Terminal tabs too); the
window is not activated and your keyboard and mouse are left alone. The
session's process id comes from `~/.claude/last-session.json`, written by the
Stop hook in `tools/save_last_answer.py`. No live session → the text is only
copied to the clipboard. Set `voice_target` to empty to paste into the focused
window instead.

- **Two stages, like the big assistants.** Siri, Alexa and Home Assistant
  spot a wake word with a small always-on model and only then understand the
  sentence with full speech recognition. whisperkey does the same: when the
  small model hears the name, the last 2.5 s plus whatever follows (until a
  0.8 s pause; a bare name waits 1.5 s for the rest) go to a small Whisper
  (`voice_command_model`, default `base`), and the command is the verb found
  in that sentence. So free wording works too: "dayı bir önceki bölüme dön" →
  previous, "dayı bunu oku" → read. Measured on CPU: ~0.9 s per command; on
  the GPU (`voice_command_device: cuda`) ~0.3 s, but the CUDA runtime adds
  ~700 MB of RAM. If Whisper finds no command, the first stage's verdict below
  still applies.
- **Two recognizers, one decision.** A grammar-limited recognizer only knows
  the phrases — and so maps *anything* to the nearest one. A second, free
  recognizer hears the same audio; a command counts only when its words match
  what the free one heard, word by word (or, for words the free model splits —
  "dayı" → "da iyi" — without the spaces). In testing this turned "dayım
  geldi" (rejected) apart from "dayı gönder" (accepted). While reading, the
  speaker drowns the free recognizer, so a grammar hit with confidence ≥ 0.95
  is enough there.
- **Distance.** The canceller's automatic gain and noise suppression lift a
  command said across the room; the end of a dictation is "3 × the room's own
  noise", tracked live, rather than a fixed level.
- **Tuning data.** Every command decision and every wake-like phrase heard is
  appended to `voice-log.jsonl` (ordinary speech is never written; capped at
  1 MB). That file shows how *your* voice is heard from where you sit.
- **Talking over the reading.** The grammar recognizer finishes a phrase
  before the free one; the decision waits up to 0.8 s for both. A sure
  "<name> ..." heard while reading pauses the reading at once, so a repeated
  command lands in silence.
- **Transcript (opt-in).** `voice_transcript: true` writes everything the
  listener hears to `transcripts/<date>.txt`, one timestamped line each
  (lines heard while reading are marked - they may be the speaker's echo).
  It is the small model's rough text, not Whisper's; off by default because
  the microphone is always open.
- **Echo cancellation.** The read-aloud audio is known sample for sample, so
  it is fed to WebRTC's echo canceller (via the `livekit` package) as the
  reference and removed from the microphone. In a synthetic test the echo
  dropped from RMS 3317 to 13. A command word that appears in the sentence
  being read is ignored as a second guard. Talking *over* the speaker is the
  weak spot — headphones avoid it entirely.
- **Cost.** Measured: the Vosk model takes ~105 MB of RAM, the echo canceller
  ~2 MB, the command Whisper (`base`, CPU) a few hundred MB; listening uses
  about 8 % of one CPU core. The whole tray process sits around 700 MB with
  voice commands on (300 MB without the second stage). No GPU needed.

**Setup.**

```bash
uv pip install --python .venv/Scripts/python.exe vosk livekit
curl -L -o vosk.zip https://alphacephei.com/vosk/models/vosk-model-small-tr-0.3.zip
tar -xf vosk.zip -C voices && del vosk.zip
```

For another language, take a small model from the
[Vosk model list](https://alphacephei.com/vosk/models), point `voice_model` at
it, and replace the phrases. `WHISPERKEY_VOICE_DEBUG=1` prints everything the
listener hears and the microphone level, useful for tuning.

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
| `tts_key` | read-aloud key; empty turns read-aloud off. `tts_prev_key` / `tts_next_key` move between chapters while the reading bar is up; otherwise they send `tts_prev_idle` / `tts_next_idle` (e.g. `ctrl+shift+tab` / `ctrl+tab` - a knob that also switches terminal tabs). |
| `tts_voice`, `tts_source` | the Piper voice (relative to the data folder) and the file that is read. |
| `tts_speed`, `double_tap` | reading speed (0.8–2.5) and the double-tap window in seconds (default 0.35). |
| `voice`, `voice_name`, `voice_model` | voice commands on/off, the wake name (asked on first start) and the Vosk model folder (its language picks the phrase templates). |
| `voice_silence`, `voice_phrases` | silence (s) that ends a spoken dictation; `{"action": ["phrase", ...]}` overrides — only what differs from the defaults is stored. |
| `voice_target` | JSON file naming the session (`pid`) that spoken dictation is typed into in the background; empty = paste into the focused window. |

Whisper sometimes invents a subtitle credit on trailing silence ("Altyazı
M.K.", "Thanks for watching"); a known list is cut from the end of every
transcript (`reading.drop_hallucinations`).

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

The state machine (`states.py`), shortcut parsing (`hotkeys.py`), the sound
layer (`sounds.py`) and the read-aloud text splitting (`reading.py`) are all
tested without a GUI or audio hardware.

## Requirements

- Windows 10/11 (the clipboard, tray and overlay layers are Win32)
- Python 3.10+
- NVIDIA GPU with CUDA — optional; without one it falls back to the CPU

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
The nearest open items are in [docs/ROADMAP.md](docs/ROADMAP.md); automatic
start/stop on silence is the big one, and read-aloud voices for more languages
are next.

## License

MIT — see [LICENSE](LICENSE).
