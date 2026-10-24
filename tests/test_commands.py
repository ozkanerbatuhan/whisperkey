import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whisperkey.commands import accept, echoed, grammar, phrases, strip_tail  # noqa: E402


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
        commands.configure()


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
