from __future__ import annotations

from app.pipeline.moments import (
    ClipCandidate,
    align_clip,
    clamp_score,
    compute_virality,
    dedupe,
    finalize,
    format_window,
    overlap_ratio,
    sentence_spans,
    split_windows,
)
from tests.conftest import make_words

TEXT = (
    "Tohle je první věta. Druhá věta je o penězích a investicích. Třetí věta přináší pointu! "
    "Čtvrtá věta pokračuje dál. Pátá věta je otázka? Šestá věta končí příběh."
)


def long_words(n_sentences: int = 400) -> list[dict]:
    text = " ".join(f"Věta číslo {i} má celkem sedm slov." for i in range(n_sentences))
    return make_words(text, wdur=0.35, gap=0.1, sentence_pause=0.4)


def test_sentence_spans_split_on_punctuation() -> None:
    words = make_words(TEXT)
    spans = sentence_spans(words)
    assert len(spans) == 6
    assert words[spans[0][1]]["w"] == "věta."
    assert words[spans[2][1]]["w"] == "pointu!"


def test_pause_counts_as_sentence_boundary() -> None:
    words = make_words("bez tečky tady konec dalsi slova bez tecky")
    words[3]["e"] = 1.3
    for w in words[4:]:
        w["s"] += 2.0
        w["e"] += 2.0
    assert len(sentence_spans(words)) == 2


def test_windows_cover_everything_with_overlap() -> None:
    words = long_words(400)  # ~22 minutes
    duration = words[-1]["e"]
    assert duration > 20 * 60
    windows = split_windows(words, window_s=600, overlap_s=90)
    assert len(windows) >= 3
    assert windows[0].i0 == 0
    assert windows[-1].i1 == len(words) - 1
    for a, b in zip(windows, windows[1:], strict=False):
        assert b.start < a.end, "consecutive windows must overlap"
        assert a.end - b.start >= 60
        assert b.start > a.start
    # every window starts at a sentence start
    starts = {s for s, _ in sentence_spans(words)}
    assert all(w.i0 in starts for w in windows)


def test_format_window_has_timestamps() -> None:
    words = make_words(TEXT)
    w = split_windows(words, 600, 60)[0]
    txt = format_window(words, w)
    assert txt.splitlines()[0].startswith("[0.00-")
    assert "penězích" in txt


def test_align_snaps_to_sentence_boundaries() -> None:
    words = make_words(TEXT, wdur=0.5, gap=0.2)
    # start in the middle of sentence 2, end in the middle of sentence 4
    s2 = words[5]  # "věta" in sentence 2
    s4 = words[17]  # "pokračuje" in sentence 4
    res = align_clip(words, s2["s"] + 0.1, s4["e"] - 0.1, min_len=3, max_len=60)
    assert res is not None
    start, end = res
    # sentence 2 starts with "Druhá" (index 4), sentence 4 ends with "dál." (index 18)
    assert words[4]["w"] == "Druhá" and words[18]["w"] == "dál."
    assert abs(start - (words[4]["s"] - 0.12)) < 0.11
    assert words[18]["e"] <= end <= words[18]["e"] + 0.31


def test_align_enforces_max_length() -> None:
    words = long_words(60)
    res = align_clip(words, 0, 200, min_len=10, max_len=30)
    assert res is not None
    assert res[1] - res[0] <= 30 + 0.5
    # ends right after a sentence end
    last = max((w for w in words if w["e"] <= res[1]), key=lambda w: w["e"])
    assert last["w"].endswith(".")


def test_align_extends_short_clip() -> None:
    words = long_words(60)
    res = align_clip(words, 10, 12, min_len=15, max_len=40)
    assert res is not None
    assert res[1] - res[0] >= 15 * 0.8


def test_align_respects_bounds() -> None:
    words = long_words(60)
    res = align_clip(words, 30, 50, min_len=10, max_len=40, bounds=(29.0, 60.0))
    assert res is not None
    assert res[0] >= 29.0 and res[1] <= 60.0


def test_overlap_and_dedupe() -> None:
    assert overlap_ratio((0, 10), (5, 15)) == 0.5
    assert overlap_ratio((0, 10), (20, 30)) == 0
    a = ClipCandidate(0, 30, "A", virality_score=80)
    b = ClipCandidate(10, 40, "B", virality_score=70)  # 66 % overlap -> dropped
    c = ClipCandidate(25, 55, "C", virality_score=60)  # 16 % overlap with A -> kept
    d = ClipCandidate(100, 130, "a", virality_score=50)
    e = ClipCandidate(110, 160, "A!", virality_score=40)  # same title as d nearby
    kept = dedupe([b, c, a, d, e])
    assert [k.title for k in kept] == ["A", "C", "a"]


def test_clamp_and_virality() -> None:
    assert clamp_score("85") == 85
    assert clamp_score(0.9) == 90
    assert clamp_score(8) == 80
    assert clamp_score(140) == 100
    assert clamp_score("x") == 0
    v = compute_virality({"hook": 90, "flow": 80, "value": 70, "trend": 60}, 80)
    assert 70 < v < 85


def test_finalize_sorts_and_filters() -> None:
    words = long_words(120)
    cands = [
        ClipCandidate(20, 60, "low", virality_score=40),
        ClipCandidate(200, 240, "high", virality_score=90),
        ClipCandidate(205, 245, "dup", virality_score=50),
        ClipCandidate(10_000, 10_040, "outside", virality_score=99),
    ]
    out = finalize(words, cands, "30-60", bounds=(0, words[-1]["e"]))
    assert [c.title for c in out] == ["high", "low"]
    for c in out:
        assert 30 * 0.8 <= c.duration <= 60.5
