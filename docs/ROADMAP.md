# Roadmap

## Open

### 1. Automatic start and stop (priority)

Work without holding a key: start recording when speech begins, stop and paste
when it ends.

Notes:
- Silence detection is mostly in place already — `audio.Recorder.level` gives a
  live RMS and Whisper has `vad_filter`. What is missing is a threshold plus a
  silence counter in the recording layer (e.g. 700 ms of silence = stop).
- One decision to make: listen to the microphone continuously (always ready,
  but exposed to room noise and false triggers) or put automatic mode behind a
  key. The second is safer, the first is more comfortable.
- Push-to-talk must stay. Automatic mode goes next to it, not in place of it.
- `states.py` needs a second event source: today only key events reach it, the
  silence detector would have to produce events too.

### 2. Read-aloud polish

- Only one official Turkish Piper voice exists (`tr_TR-dfki-medium`); try
  community voices or a second engine for languages where Piper is thin.
- What gets read is a first cut (`speaker.clean`): code blocks, tables and
  links are dropped. Tune it from real listening.
- Seeking lands on the start of a sentence; mid-sentence seeking would need
  the sample offset kept for not-yet-rendered sentences.
- A settings page for the `tts_*` keys (they are config-only today).

## Done

### Read aloud (text to speech)

The other direction: a key reads a text file aloud with a local
[Piper](https://github.com/OHF-Voice/piper1-gpl) voice, in the same process
and the same overlay as dictation.

- Measured first: edge-tts (Microsoft's online voices) sounded best but
  returned no audio on 5 of 8 requests in a row — unusable for "press and it
  speaks". Piper renders the first sentence in ~0.1 s once warm (warm-up
  ~1.7 s happens at startup), entirely offline.
- Sentences are rendered by one background thread while the audio callback
  plays; a speed change re-renders the current sentence and jumps to the same
  relative position, so it is heard at once.
- Headings and bold-label paragraphs become chapters; the overlay draws them
  as separate segments. Click to seek, − / + for speed, a key per
  previous / next chapter.
- Tap = play / pause / resume, double tap = media play/pause (so the same
  physical key still controls music). Dictation pauses the reading.

### Sounds

`winsound.Beep` played square waves and sounded harsh. Replaced with
sine-based wavs whose upper harmonics decay quickly:
`src/whisperkey/assets/sounds/{start,stop,done,fail}.wav` — 90 ms for
start/stop, 120 ms for done, 200 ms for fail (longer on purpose).

- The generator is `tools/make_sounds.py`; pitch, harmonic weights and decay
  live there. Change the sounds there, not by editing the wavs.
- `sounds.py` reads the wav into memory and plays it with
  `SND_MEMORY | SND_ASYNC`: no disk access per play, and volume is scaled
  without touching the file.
- Added the `sound_volume` setting (0-1) and a preview button in Settings.
- If a wav is missing it falls back to the old tones.

### Rebindable shortcuts

The three fields under Settings → Shortcuts are not text boxes: click one and
press the key. Combinations work (Ctrl+Shift+F9), Esc cancels.

- Capture is `hotkeys.KeyCapture`. `keyboard.read_hotkey` was not used because
  it cannot be cancelled — closing the window would leave the hook dangling.
- The application's global hooks are removed during capture and rebound after,
  otherwise the key being captured would also start a recording.
- Because the talk key is suppressed globally, a bare letter or digit is
  rejected — that character could never be typed anywhere again.
- The same shortcut cannot be assigned to two jobs; this is checked on save.
- `add_hotkey` does not give press and release together, so the talk key hooks
  the main key and checks modifiers by hand (`Hotkeys.mods_held`). If the
  shortcut itself contains Ctrl, Ctrl no longer means copy-only.

### Tray panel

A left click opens a one-screen panel next to the cursor; it closes on focus
loss and on Esc. The right-click menu is unchanged.

- Contents: status dot and text, engine state with an unload link, a language
  segment, overlay / sound / keep-warm switches, a shortcut reminder, plus
  Settings and Quit.
- It is not a shrunken settings window - separate module, `ui/panel.py`.
- The visual language comes from `ui/theme.py`.
- Clicking the tray icon takes focus away from the panel first; a 350 ms guard
  keeps the following toggle from reopening it.
