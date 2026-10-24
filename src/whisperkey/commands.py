"""Voice commands: which phrases are listened for, and whether a hit is real.

Pure and dependency free, like `states.py`. The audio side is `listener.py`.

Two recognizers hear the same audio. The grammar one only knows the command
phrases, so it maps *anything* to the nearest command ("dayım geldi" became
"dayı gönder" in testing). The free one transcribes normally. A command counts
only when the free transcript sounds like it too.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# action -> phrase templates per language; {name} is the wake name the user
# picks on first start. The language must match the Vosk model's.
TEMPLATES = {
    "tr": {
        "dictate": ["{name} dinle"],
        "read": ["{name} oku"],
        "next": ["sonraki", "bir sonraki"],
        "prev": ["önceki", "bir önceki"],
        "pause": ["dur", "okumayı durdur", "{name} dur"],
        "resume": ["devam", "devam et", "okumayı başlat"],
        "done": ["{name} tamam"],
        "send": ["{name} gönder"],
        "cancel": ["{name} iptal"],
        "close": ["{name} kapat", "{name} oturumu kapat"],
    },
    "en": {
        "dictate": ["{name} listen"],
        "read": ["{name} read"],
        "next": ["next", "next part"],
        "prev": ["previous", "go back"],
        "pause": ["stop", "pause", "{name} stop"],
        "resume": ["resume", "continue"],
        "done": ["{name} done"],
        "send": ["{name} send"],
        "cancel": ["{name} cancel"],
        "close": ["{name} close", "{name} exit"],
    },
}
WAKE_ACTIONS = ("dictate", "read", "close")
READING_ACTIONS = ("next", "prev", "pause", "resume")
DICTATING_ACTIONS = ("done", "send", "cancel")

WAKE: dict[str, str] = {}
READING: dict[str, str] = {}
DICTATING: dict[str, str] = {}


def language_of(model_path: str) -> str:
    """Template language from the Vosk model folder name (vosk-model-small-tr-0.3)."""
    parts = re.split(r"[-_./\\]", model_path.lower())
    return next((p for p in parts if p in TEMPLATES), "en")


def defaults(name: str, lang: str = "tr") -> dict[str, list[str]]:
    """Phrases for a wake name. Without a name, phrases that need one are left
    out - a bare "listen" would fire on every sentence that contains it."""
    name = norm(name)
    table = TEMPLATES.get(lang, TEMPLATES["en"])
    return {a: [norm(t.format(name=name)) for t in items if name or "{name}" not in t]
            for a, items in table.items()}


def configure(mapping: dict | None = None, name: str = "", lang: str = "tr") -> None:
    """Load phrases: the language's templates with `name`, then overrides
    (action -> list of phrases) from the config."""
    table = defaults(name, lang)
    for action, items in (mapping or {}).items():
        if action in table:
            table[action] = [norm(p) for p in items if norm(p)]
    for target, actions in ((WAKE, WAKE_ACTIONS), (READING, READING_ACTIONS),
                            (DICTATING, DICTATING_ACTIONS)):
        target.clear()
        target.update({p: a for a in actions for p in table[a]})

MIN_SIMILARITY = 0.65
MIN_JOINED = 0.8
MIN_CONFIDENCE = 0.7
MIN_CONFIDENCE_ALONE = 0.95


def phrases(state: str) -> dict[str, str]:
    """Commands that make sense in a state: idle | reading | dictating.

    "send" is heard everywhere: people pause before saying it, the silence
    ends the dictation first, and the send must still go through (the app
    only honours it right after a dictation was typed).
    """
    send = {p: a for p, a in DICTATING.items() if a == "send"}
    if state == "dictating":
        return dict(DICTATING)
    if state == "reading":
        return {**WAKE, **READING, **send}
    return {**WAKE, **send}


def grammar(state: str) -> list[str]:
    return [*phrases(state), "[unk]"]


def norm(text: str) -> str:
    """Lowercase, Turkish-aware, punctuation and accents of i folded."""
    text = text.replace("İ", "i").replace("I", "ı").lower()
    text = unicodedata.normalize("NFC", text)
    text = text.replace("i̇", "i")
    return " ".join(re.findall(r"\w+", text))


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def accept(command: str, confidences: list[float], free_text: str) -> bool:
    """Is a grammar hit real? The free transcript's tail must sound alike."""
    if command not in {**WAKE, **READING, **DICTATING}:
        return False
    if confidences and min(confidences) < MIN_CONFIDENCE:
        return False
    said = norm(free_text).split()
    want = norm(command).split()
    if not said:
        return False
    # word by word against the end of what was said: "dayım geldi" shares
    # letters with "dayı gönder" as a whole, but "geldi" is no "gönder"
    if len(said) >= len(want):
        tail = said[-len(want):]
        if all(similar(w, s) >= MIN_SIMILARITY for w, s in zip(want, tail, strict=True)):
            return True
    # the free model splits words it does not know: "dayı dinle" -> "da iyi
    # dinle". Compare without spaces against one word more, more strictly.
    # The start must match too: "kapıyı kapat" is close to "dayıkapat" as a
    # whole, but it does not begin like the wake name.
    joined = "".join(want)
    for k in (len(want) + 1, len(want) + 2):
        if k > len(said):
            continue
        tail = "".join(said[-k:])
        if tail[:2] == joined[:2] and similar(joined, tail) >= MIN_JOINED:
            return True
    return False


def trusted_alone(confidences: list[float]) -> bool:
    """While reading, the speaker drowns the free recognizer; a very sure
    grammar hit is enough there (the echo check still applies)."""
    return bool(confidences) and min(confidences) >= MIN_CONFIDENCE_ALONE


def sounds_like_wake(text: str) -> bool:
    """Free transcript that resembles a wake phrase - worth logging for tuning."""
    words = norm(text).split()
    for phrase in WAKE:
        first = phrase.split()[0]
        if any(similar(first, w) >= MIN_SIMILARITY for w in words):
            return True
    return False


def echoed(command: str, playing_text: str) -> bool:
    """The command word is in what the speaker is saying right now: our own echo."""
    return bool(playing_text) and f" {norm(command)} " in f" {norm(playing_text)} "


def strip_tail(text: str) -> str:
    """Drop the closing command ("Dayı tamam") that Whisper also transcribed."""
    words = list(re.finditer(r"\w+", text))
    for phrase in sorted(DICTATING, key=lambda p: -len(p.split())):
        want = phrase.split()
        if len(words) < len(want):
            continue
        tail = words[-len(want):]
        if all(similar(w, m.group()) >= MIN_SIMILARITY
               for w, m in zip(want, tail, strict=True)):
            return text[:tail[0].start()].rstrip(" \t,;:-")
    return text


configure()
