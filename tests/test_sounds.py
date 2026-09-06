import io
import sys
import wave
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whisperkey.sounds import KINDS, SOUND_DIR, Sounds, _scaled  # noqa: E402


def _peak(data: bytes) -> int:
    with wave.open(io.BytesIO(data), "rb") as w:
        samples = array("h")
        samples.frombytes(w.readframes(w.getnframes()))
    return max(abs(v) for v in samples)


def test_every_sound_is_shipped():
    for kind in KINDS:
        assert (SOUND_DIR / f"{kind}.wav").exists(), kind


def test_sounds_are_short():
    # a long sound breaks the flow of speech; the failure tone is longer on purpose
    limits = {"start": 0.12, "stop": 0.12, "done": 0.15, "fail": 0.25}
    for kind, limit in limits.items():
        with wave.open(str(SOUND_DIR / f"{kind}.wav"), "rb") as w:
            assert w.getnframes() / w.getframerate() <= limit, kind


def test_volume_scales_samples():
    full = _scaled(SOUND_DIR / "done.wav", 1.0)
    half = _scaled(SOUND_DIR / "done.wav", 0.5)
    assert _peak(half) < _peak(full)
    assert abs(_peak(half) * 2 - _peak(full)) <= 2


def test_volume_change_clears_cache():
    s = Sounds(volume=1.0)
    first = s._data("done")
    s.set_volume(0.25)
    assert s._data("done") != first


def test_missing_file_falls_back_without_raising(tmp_path):
    s = Sounds(volume=0.5, directory=tmp_path)
    assert not s.available()
    assert s._data("done") is None      # falls back to a tone instead of raising
