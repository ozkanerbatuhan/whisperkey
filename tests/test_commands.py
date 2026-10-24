import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whisperkey import commands  # noqa: E402
from whisperkey.commands import accept, echoed, grammar, phrases, strip_tail  # noqa: E402

commands.configure(name="dayı", lang="tr")


def test_reading_words_only_while_reading():
    assert "sonraki" not in phrases("idle")
    assert "sonraki" in phrases("reading")
    assert set(phrases("dictating")) == {"dayı tamam", "dayı gönder", "dayı iptal"}
    assert grammar("idle")[-1] == "[unk]"


def test_free_transcript_must_agree():
    # forced matches seen in testing: the free recognizer heard something else
    assert not accept("dayı gönder", [1.0, 1.0], "dayım geldi")
    assert not accept("sonraki", [1.0], "sonra bakarız")
    # near misses of the free recognizer still count
    assert accept("dur", [1.0], "dür")
    assert accept("dayı dinle", [0.98, 1.0], "dayı dinle")
    assert accept("dayı tamam", [0.9, 1.0], "bunu yarın yaparız dayı tamam")


def test_low_confidence_is_rejected():
    assert not accept("sonraki", [0.4], "sonraki")


def test_echo_of_our_own_reading():
    assert echoed("sonraki", "Şimdi sonraki bölüme geçiyoruz.")
    assert not echoed("sonraki", "Bölüm bitti.")
    assert not echoed("dur", "Durum iyi.")


def test_strip_closing_command():
    assert strip_tail("Bunu yarın yaparız. Dayı, tamam.") == "Bunu yarın yaparız."
    assert strip_tail("mesajı yolla dayı gönder") == "mesajı yolla"
    assert strip_tail("tamam dedim ona") == "tamam dedim ona"


def test_phrases_are_configurable():
    from whisperkey import commands

    commands.configure({"dictate": ["hey listen"], "done": ["over"]})
    try:
        assert phrases("idle")["hey listen"] == "dictate"
        assert "dayı dinle" not in phrases("idle")
        assert phrases("dictating")["over"] == "done"
        assert strip_tail("see you tomorrow, over") == "see you tomorrow"
    finally:
        commands.configure(name="dayı", lang="tr")


def test_wake_name_fills_the_templates():
    try:
        commands.configure(name="Jarvis", lang="en")
        assert phrases("idle")["jarvis listen"] == "dictate"
        assert phrases("dictating")["jarvis send"] == "send"
        commands.configure(name="", lang="tr")
        assert phrases("idle") == {}            # no name, no wake phrases
        assert "sonraki" in phrases("reading")  # name-free ones stay
    finally:
        commands.configure(name="dayı", lang="tr")


def test_close_session_phrase():
    assert phrases("idle")["dayı kapat"] == "close"
    assert phrases("reading")["dayı oturumu kapat"] == "close"
    assert "dayı kapat" not in phrases("dictating")
    assert accept("dayı kapat", [1.0, 1.0], "da iyi kapat")
    assert not accept("dayı kapat", [1.0, 1.0], "kapıyı kapat")


def test_language_from_model_folder():
    assert commands.language_of("voices/vosk-model-small-tr-0.3") == "tr"
    assert commands.language_of("voices/vosk-model-small-en-us-0.15") == "en"
    assert commands.language_of("voices/vosk-model-small-de-0.15") == "en"


def test_split_wake_word_still_counts():
    # the free model writes "dayı" as "da iyi" or "da"
    assert accept("dayı dinle", [1.0, 1.0], "da iyi dinle")
    assert accept("dayı dinle", [1.0, 1.0], "da dinle")
    assert not accept("dayı oku", [1.0, 1.0], "daha iyi oku")


def test_send_is_heard_outside_dictation():
    assert phrases("idle")["dayı gönder"] == "send"
    assert phrases("reading")["dayı gönder"] == "send"
    assert "dayı tamam" not in phrases("idle")


def test_sure_grammar_hit_alone():
    from whisperkey.commands import trusted_alone

    assert trusted_alone([1.0])
    assert not trusted_alone([0.59, 1.0])


def test_addresses_me_only_with_the_name():
    from whisperkey.commands import addresses_me

    assert addresses_me("dayı kapat")
    assert addresses_me("dayı gönder")
    assert not addresses_me("sonraki")


def test_second_stage_intent_from_free_sentence():
    from whisperkey.commands import intent

    assert intent("dayı oturmuk kapat.", "idle") == "close"       # Whisper's typo
    assert intent("dayı bir önceki bölümede.", "reading") == "prev"
    assert intent("dahi bunu oku.", "idle") == "read"
    assert intent("dayı okumayı durdur", "reading") == "pause"
    assert intent("bugün hava güzel", "idle") is None
    assert intent("sonraki", "idle") is None                      # reading words only while reading
