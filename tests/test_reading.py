import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whisperkey.reading import chapters, clean, sentences  # noqa: E402


def test_bold_labels_become_chapters():
    raw = "Short answer first.\n\n**Button:** tap to read.\n\n**Bar:** click to seek. Second line."
    got = chapters(raw)
    assert [t for t, _ in got] == ["Short answer first.", "Button", "Bar"]
    assert got[2][1] == "click to seek. Second line."


def test_headings_become_chapters_and_code_is_dropped():
    raw = "## Plan\n\nDo it.\n\n```\nx = 1\n```\n\n## Result\n\nDone."
    got = chapters(raw)
    assert [t for t, _ in got] == ["Plan", "Result"]
    assert "x = 1" not in got[0][1]


def test_unmarked_paragraphs_each_become_a_chapter():
    got = chapters("One two three four five six.\n\nSecond.")
    assert got[0][0] == "One two three four five…"
    assert len(got) == 2


def test_clean_strips_markdown():
    assert clean("**bold** `code` [link](http://x)") == "bold code link"
    assert sentences("A b. C d? E") == ["A b.", "C d?", "E"]


def test_whisper_outro_is_dropped():
    from whisperkey.reading import drop_hallucinations

    assert drop_hallucinations("Bunu yarın yaparız. Altyazı M.K.") == "Bunu yarın yaparız."
    assert drop_hallucinations("Altyazı M.K.") == ""
    assert drop_hallucinations("Thanks for watching!") == ""
    assert drop_hallucinations("Tamam. İzlediğiniz için teşekkürler.") == "Tamam."
    assert drop_hallucinations("altyazıyı açar mısın") == "altyazıyı açar mısın"
