"""Always-on voice commands: a small Vosk model listens for "Dayı ..." phrases.

Pipeline, one 10 ms frame at a time:

  microphone ─> echo canceller ─> grammar recognizer ─┐
                (WebRTC AEC)  └─> free recognizer ────┴─> commands.accept ─> on_command
  speaker output ─> reverse stream of the canceller

The read-aloud audio is known sample for sample, so it is fed to the canceller
as the far-end reference and removed from the microphone signal - otherwise
the speaker reading "sonraki" would trigger "next" by itself. A text check
(`commands.echoed`) backs it up.

Memory: ~105 MB for the Vosk model, ~2 MB for the canceller (measured).
Only the 10-15 command phrases are decided on; nothing else is kept.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

from . import commands

RATE = 16000
FRAME = RATE // 100                 # 10 ms, what the canceller wants
CHUNK = 10                          # frames per recognizer call (100 ms)
SPEECH_RATIO = 3.0                  # speech = this many times the room noise...
SPEECH_FLOOR = 150                  # ...and at least this loud (int16 RMS, after AEC)
DEBUG = bool(os.environ.get("WHISPERKEY_VOICE_DEBUG"))  # print everything heard
CAPTURE_BEFORE = 2.5                # s of audio kept from before the name was recognized
CAPTURE_GRACE = 1.5                 # s to start talking after a bare name
CAPTURE_PAUSE = 0.8                 # s of quiet that ends the command sentence
CAPTURE_MAX = 5.0                   # s, longest command sentence


class Listener:
    def __init__(self, model_path: str, on_command, device=None, log_path=None,
                 transcript_dir=None, command_model: str = "", model_dir=None,
                 language: str = "tr", command_device: str = "cpu"):
        self.model_path = model_path
        # second stage: a small Whisper on the CPU reads the sentence after
        # the wake name ("" = first stage only)
        self.command_model = command_model
        self.command_device = command_device    # cpu | cuda | auto
        self.model_dir = model_dir
        self.language = language
        self._model = None
        self._model_lock = threading.Lock()
        self._ring: deque = deque(maxlen=int(CAPTURE_BEFORE * 100))   # 10 ms frames
        self._capture = None
        self._capture_done = None
        self._capture_started = 0.0
        self._capture_result: dict = {}
        self._capture_state = "idle"
        self._capture_grace = 0.0
        self.log_path = log_path                # command decisions, for tuning (jsonl)
        self.transcript_dir = transcript_dir    # everything heard, per day (opt-in)
        self._pending = None                    # (time, grammar result) awaiting the free one
        self.on_command = on_command            # on_command(action, phrase)
        self.device = device
        self.state = "idle"                     # idle | reading | dictating
        self.playing_text = ""                  # sentence the speaker is saying
        self.last_speech = 0.0                  # monotonic time of the last loud frame
        self._mic: queue.Queue = queue.Queue(maxsize=500)
        self._far: deque = deque()              # 16 kHz int16 samples from the speaker
        self._far_lock = threading.Lock()
        self._stream = None
        self._running = False
        self._grammar_state = None
        self._recent: deque = deque(maxlen=6)   # (time, free final text)
        self._peak_rms = 0.0
        self._level_at = 0.0
        self._noise = 100.0                     # running estimate of the room's RMS
        self._partial = ""

    # ------------------------------------------------------------ speaker tap

    def feed_far(self, samples: np.ndarray, rate: int) -> None:
        """Called from the speaker's audio callback with what it just played."""
        if not self._running or not len(samples):
            return
        n = int(len(samples) * RATE / rate)
        idx = np.linspace(0, len(samples) - 1, n)
        res = np.interp(idx, np.arange(len(samples)), samples.astype(np.float32))
        with self._far_lock:
            self._far.extend(res.astype(np.int16).tolist())
            # never let the reference run far ahead (e.g. after a pause)
            while len(self._far) > RATE:
                self._far.popleft()

    def _far_frame(self) -> np.ndarray:
        with self._far_lock:
            if len(self._far) >= FRAME:
                return np.array([self._far.popleft() for _ in range(FRAME)], np.int16)
        return np.zeros(FRAME, np.int16)

    # ------------------------------------------------------------ run

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._running = False

    def _callback(self, indata, frames, _time, _status) -> None:
        try:
            self._mic.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass                                # recognizer fell behind; drop

    def _run(self) -> None:
        from livekit import rtc
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        model = Model(self.model_path)
        free = KaldiRecognizer(model, RATE)
        gram = None
        # auto gain: a command said from across the room arrives several times
        # quieter than one said into the microphone
        apm = rtc.AudioProcessingModule(echo_cancellation=True, high_pass_filter=True,
                                        noise_suppression=True, auto_gain_control=True)
        try:
            self._stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16",
                                          blocksize=FRAME, device=self.device,
                                          callback=self._callback)
            self._stream.start()
        except Exception as exc:
            print(f"[warning] voice commands off - microphone did not open: {exc}")
            self._running = False
            return
        print("[whisperkey] voice commands on")

        batch: list[bytes] = []
        while self._running:
            try:
                mic = self._mic.get(timeout=0.5)
            except queue.Empty:
                continue
            if len(mic) != FRAME:
                continue
            far = rtc.AudioFrame(self._far_frame().tobytes(), RATE, 1, FRAME)
            apm.process_reverse_stream(far)
            frame = rtc.AudioFrame(mic.tobytes(), RATE, 1, FRAME)
            apm.process_stream(frame)
            clean = bytes(frame.data.cast("B"))
            pcm = np.frombuffer(clean, np.int16)
            rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
            self._peak_rms = max(self._peak_rms, rms)
            # speech = clearly above the room's own noise, whatever the microphone
            if rms < self._noise * 2:
                self._noise = 0.995 * self._noise + 0.005 * rms
            if rms > max(SPEECH_FLOOR, SPEECH_RATIO * self._noise):
                self.last_speech = time.monotonic()
            self._ring.append(pcm)
            if self._capture is not None:
                self._capture.append(pcm)
                self._capture_tick()
            batch.append(clean)
            if len(batch) < CHUNK:
                continue
            chunk, batch = b"".join(batch), []

            if self._grammar_state != self.state or gram is None:
                gram = KaldiRecognizer(model, RATE, json.dumps(commands.grammar(self.state),
                                                              ensure_ascii=False))
                gram.SetWords(True)
                self._grammar_state = self.state

            free_final = free.AcceptWaveform(chunk)
            if free_final:
                text = json.loads(free.Result()).get("text", "")
                if text:
                    self._recent.append((time.monotonic(), text))
                    if DEBUG:
                        print(f"[voice] heard: {text!r}")
                    if commands.sounds_like_wake(text):
                        self._log("heard", text)
                    self._transcribe(text)
                self._partial = ""
            else:
                # words still coming = still talking, even if quietly
                partial = json.loads(free.PartialResult()).get("partial", "")
                if partial != self._partial:
                    self._partial = partial
                    if partial:
                        self.last_speech = time.monotonic()
            if gram.AcceptWaveform(chunk):
                result = json.loads(gram.Result())
                text = result.get("text", "")
                if self._capture is not None:
                    pass                        # the second stage is already listening
                elif (self.command_model and self.state != "dictating"
                        and commands.addresses_me(text)):
                    # "<name> ...": hand the sentence to Whisper (second stage)
                    self._start_capture(result)
                elif text in commands.phrases(self.state):
                    # the grammar recognizer finishes first; give the free one a
                    # moment to finish the same words before judging
                    self._pending = (time.monotonic(), result)
                    self._attention(result)
            if self._capture_done is not None:
                self._second_stage(*self._capture_done, free)
                self._capture_done = None
            if self._pending and (free_final or time.monotonic() - self._pending[0] > 0.8):
                result, self._pending = self._pending[1], None
                self._decide(result, free)
            if DEBUG and time.monotonic() - self._level_at > 5:
                self._level_at = time.monotonic()
                print(f"[voice] mic peak rms={self._peak_rms:.0f} noise={self._noise:.0f}")
                self._peak_rms = 0.0

        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass

    # ------------------------------------------------------------ second stage

    def _start_capture(self, result: dict) -> None:
        """The name was heard: keep the last seconds (the name and whatever
        followed it is already in the past) and listen on until a pause."""
        self._attention(result, force=True)
        self.on_command("wake", result.get("text", ""))
        self._capture = list(self._ring)[-int(CAPTURE_BEFORE * 100):]
        self._capture_started = time.monotonic()
        # a bare name ("dayı" ... pause ... "kapat") waits a moment for the rest
        bare = len(result.get("text", "").split()) == 1
        self._capture_grace = CAPTURE_GRACE if bare else 0.0
        self._capture_result = result
        self._capture_state = self.state

    def _capture_tick(self) -> None:
        now = time.monotonic()
        # a whole phrase ("dayı kapat") was already over when it was recognized:
        # end as soon as it is quiet; a bare name waits for the rest
        if self._capture_grace:
            quiet = now - max(self.last_speech, self._capture_started + self._capture_grace)                 > CAPTURE_PAUSE
        else:
            quiet = now - self.last_speech > CAPTURE_PAUSE
        if quiet or now - self._capture_started > CAPTURE_MAX:
            audio = np.concatenate(self._capture).astype(np.float32) / 32768.0
            self._capture = None
            self._capture_done = (audio, self._capture_result, self._capture_state)

    def _second_stage(self, audio, result: dict, state: str, free) -> None:
        """Whisper reads the captured sentence; the verb in it is the command.
        If Whisper finds none, the first stage's own verdict still applies."""
        heard = " ".join(t for at, t in self._recent if time.monotonic() - at < 6.0)
        heard += " " + json.loads(free.PartialResult()).get("partial", "")

        def work():
            text = self._whisper(audio)
            action = commands.intent(text, state) if text else None
            phrase = result.get("text", "")
            conf = [w.get("conf", 1.0) for w in result.get("result", [])]
            if action is None and phrase in commands.phrases(state):
                if commands.accept(phrase, conf, heard):
                    action = commands.phrases(state)[phrase]
            print(f"[voice] second stage: {text!r} -> {action}")
            self._log("whisper", text, action or "", conf)
            if action:
                self._recent.clear()
                self.on_command(action, text)
            else:
                self.on_command("unheard", text)

        threading.Thread(target=work, daemon=True).start()

    def _whisper(self, audio) -> str:
        with self._model_lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                from .engine import _enable_cuda_dlls, cuda_available

                # measured with "base": CPU int8 ~0.9 s per command, process RAM
                # ~450 MB; GPU ~0.3 s, but the CUDA runtime adds ~700 MB of RAM
                gpu = self.command_device == "cuda" or (
                    self.command_device == "auto" and cuda_available())
                if gpu:
                    _enable_cuda_dlls()
                self._model = WhisperModel(self.command_model,
                                           device="cuda" if gpu else "cpu",
                                           compute_type="float16" if gpu else "int8",
                                           download_root=self.model_dir)
            names = ", ".join(sorted(commands.wake_names()))
            prompt = ", ".join(list(commands.WAKE) + list(commands.READING)[:4]) or names
            try:
                segs, _ = self._model.transcribe(audio, language=self.language,
                                                 beam_size=1, vad_filter=False,
                                                 initial_prompt=prompt)
                return " ".join(s.text.strip() for s in segs).strip()
            except Exception as exc:
                print(f"[warning] command transcription failed: {exc}")
                return ""

    def warm_command_model(self) -> None:
        if self.command_model:
            threading.Thread(target=lambda: self._whisper(np.zeros(RATE, np.float32)),
                             daemon=True).start()

    def _attention(self, result: dict, force: bool = False) -> None:
        """While reading, a sure "<name> ..." means you are talking to it: stop
        talking over you at once, so the command is heard in silence (the
        decision itself comes a moment later, and may still say no)."""
        if self.state != "reading" or not self.playing_text:
            return
        phrase = result.get("text", "")
        conf = [w.get("conf", 1.0) for w in result.get("result", [])]
        if force or (commands.addresses_me(phrase) and conf and min(conf) >= 0.9):
            self.on_command("attention", phrase)

    def _transcribe(self, text: str) -> None:
        """Everything the free recognizer heard, one line each, per day (opt-in).
        Lines heard while the speaker reads are marked: they may be its echo."""
        if not self.transcript_dir:
            return
        try:
            os.makedirs(self.transcript_dir, exist_ok=True)
            path = os.path.join(self.transcript_dir, time.strftime("%Y-%m-%d") + ".txt")
            mark = " [reading]" if self.playing_text else ""
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')}{mark} {text}\n")
        except OSError:
            pass

    def _log(self, kind: str, heard: str, phrase: str = "", conf=()) -> None:
        """One line per command decision or wake-like phrase: the tuning data.

        Only these few lines are written - never ordinary speech. Capped at
        ~1 MB, then it starts over.
        """
        if not self.log_path:
            return
        try:
            if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > 1_000_000:
                os.replace(self.log_path, self.log_path + ".old")
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind,
                                    "state": self.state, "phrase": phrase,
                                    "conf": [round(c, 2) for c in conf], "heard": heard,
                                    "noise": round(self._noise)}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _decide(self, result: dict, free) -> None:
        phrase = result.get("text", "")
        table = commands.phrases(self.state)
        if phrase not in table:
            return
        conf = [w.get("conf", 1.0) for w in result.get("result", [])]
        now = time.monotonic()
        heard = " ".join(t for at, t in self._recent if now - at < 4.0)
        heard += " " + json.loads(free.PartialResult()).get("partial", "")
        ok = commands.accept(phrase, conf, heard)
        if self.state == "reading":
            if commands.echoed(phrase, self.playing_text):
                print(f"[voice] ignored '{phrase}' - it is in the sentence being read")
                self._log("echo", heard.strip(), phrase, conf)
                return
            # the free recognizer hears the speaker more than you while reading
            # (reading controls only - closing a session needs both to agree)
            ok = ok or (table[phrase] in commands.READING_ACTIONS
                        and commands.trusted_alone(conf))
        print(f"[voice] {phrase!r} conf={[round(c, 2) for c in conf]} "
              f"free={heard.strip()!r} -> {'yes' if ok else 'no'}")
        self._log("accepted" if ok else "rejected", heard.strip(), phrase, conf)
        if ok:
            self._recent.clear()
            self.on_command(table[phrase], phrase)
