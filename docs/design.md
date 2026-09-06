# Design notes

Why the code looks the way it does. Every number here was measured on one
machine: Windows 11, RTX 3050 Ti (4 GB), large-v3-turbo.

## The problem

Dictation that is actually usable has to satisfy three things at once: it must
be fast enough that talking beats typing, cheap enough at rest that you leave
it running all day, and private enough that you can dictate anything. Cloud
services fail the third, and a resident local model fails the second.

## Why the engine has its own process

`Engine.unload()` frees the VRAM but not the RAM: the process stays around
670 MB, because the allocator does not return its arena to the operating
system. Calling it did not solve the idle-cost problem.

Ending the process does. So the split is:

- **parent** — tray, overlay, settings, keyboard hooks. 61 MB, always on.
  About half of that is tkinter and the tray icon.
- **child** — faster-whisper. Born on the first utterance, killed after
  `idle_unload_sec` of silence (300 s by default).

The child is fired the *moment recording starts*, not when the audio is ready,
so model loading overlaps with speech. That is what turns a 12-second cold
start into roughly 6.

| | RAM | VRAM |
|---|---|---|
| idle | 61 MB | 0 MB |
| engine up | +674 MB | +2243 MB |

## Why float16 by default

| precision | VRAM | load |
|---|---|---|
| float16 | 2243 MB | 5.4 s |
| int8_float16 | 1187 MB | 9.4 s |

Transcription speed is the same. So `compute_type: auto` takes float16 when
more than 3 GB of VRAM is free and drops to int8_float16 when the GPU is busy
with a game or a CAD session. The fallback chain continues to the CPU if CUDA
fails to open at all — and it prints why, because a silent fallback to the CPU
looks like "it just got slow".

## Threads

```
main thread   tkinter: overlay, panel, settings. All UI work.
tray thread   pystray.
hook thread   keyboard callbacks. Must stay short.
worker        single consumer: transcription and pasting.
```

No thread other than the main one touches the UI; everything goes through
`App.ui_q` and is drained by `_pump` every 33 ms. The worker is single —
utterances keep their order even when you talk faster than the model runs.

`states.py` deliberately knows nothing about audio, tkinter or the keyboard
library. It takes a timestamp and returns an action, which makes the whole
hold / tap / cancel behavior testable on a CI runner with no hardware.

## Pasting, not typing

Sending keystrokes for every character is slow and breaks on non-ASCII input
methods. Instead the text goes onto the clipboard and a single Ctrl+V is sent,
after which the previous clipboard contents are restored (~350 ms later; doing
it sooner would paste the old text).

Win32 clipboard calls are used directly rather than pyperclip: when another
process holds the clipboard we can retry and then report an honest failure
instead of swallowing it.

The overlay must never take focus — if it does, Ctrl+V lands in the overlay
instead of the target window. So it is marked `WS_EX_NOACTIVATE` and shown with
`SW_SHOWNOACTIVATE`, because tkinter's `deiconify` steals focus.

## The talk key is suppressed

The talk key is swallowed globally, so the application can tell a hold from a
tap without the key also reaching the focused window. That has a consequence:
a bare letter with no modifier is rejected as a shortcut, because it could
never be typed anywhere again.

Esc is the opposite case and is deliberately *not* suppressed — swallowing it
globally would lock up terminals and editors.

## Why Python, not Rust

The first instinct was Rust, for the memory footprint. Measurement moved the
argument: the idle cost comes from model weights held in memory, not from the
language, and those weights occupy the same space whichever language allocates
them. Once the engine gets its own process and dies when idle, the interface
sits at 61 MB — half of it tkinter and the tray icon. Rust would save something
like 40 MB.

Against that, `whisper-rs` wants a build from source: cmake, MSVC, the CUDA
toolkit. Small gain, large cost.

## On the initial prompt

`initial_prompt` shows the model the speaking style to expect. It measurably
improves how English technical terms are spelled inside a sentence in another
language — the exact case that Whisper gets wrong on its own. It is the one
setting worth personalizing with your own vocabulary.

If you change it, re-test with the words that used to break. The quality claim
rests on that test, not on the setting existing.
