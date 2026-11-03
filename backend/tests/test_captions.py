from __future__ import annotations

import itertools
import re

from app.pipeline import captions
from app.pipeline.captions import (
    apply_word_edits,
    ass_color,
    ass_time,
    build_ass,
    build_srt,
    caption_events,
    group_words,
    keyword_match,
)
from app.pipeline.presets import builtin_ids, load_presets_file, resolve_style
from app.pipeline.timeline import build_timemap, is_filler, map_words
from tests.conftest import make_words

CZ = "Příliš žluťoučký kůň úpěl ďábelské ódy. Řeč o penězích, ěščřžýáíéůú ĚŠČŘŽÝÁÍÉŮÚ!"


def test_at_least_12_presets_and_all_render() -> None:
    ids = builtin_ids()
    assert len(ids) >= 12
    for required in ("bold-pop", "karaoke", "minimal", "neon-glow", "box", "typewriter", "bounce", "gradient",
                     "comic", "podcast-clean", "emoji", "highlight-keywords"):
        assert required in ids
    words = make_words(CZ)
    for pid in ids:
        style = resolve_style(pid)
        doc = build_ass(words, style, 1080, 1920, keywords=["peníze"], hook_text="Háček 😱")
        assert "[Events]" in doc and "Dialogue:" in doc, pid
        font = next(f for f in load_presets_file()["fonts"] if f["id"] == style["font"])
        assert f",{font['family']}," in doc


def test_czech_diacritics_preserved_in_ass_and_srt(tmp_dir) -> None:  # type: ignore[no-untyped-def]
    words = make_words(CZ)
    style = resolve_style("bold-pop")  # uppercase preset
    doc = build_ass(words, style, 1080, 1920)
    for ch in "ĚŠČŘŽÝÁÍÉŮÚŤĎŇ":
        assert ch in doc, ch
    assert "ŘEČ" in doc and "PENĚZÍCH" in doc
    p = tmp_dir / "c.ass"
    p.write_text(doc, encoding="utf-8")
    assert "ŽLUŤOUČKÝ".encode() in p.read_bytes()

    srt = build_srt(words)
    assert "Příliš žluťoučký kůň" in srt
    assert re.search(r"^1\n00:00:00,000 --> 00:00:0\d,\d{3}\n", srt)
    (tmp_dir / "c.srt").write_text(srt, encoding="utf-8")
    assert (tmp_dir / "c.srt").read_bytes().decode("utf-8") == srt


def test_minimal_keeps_case() -> None:
    doc = build_ass(make_words(CZ), resolve_style("minimal"), 1080, 1920)
    assert "Příliš" in doc


def test_grouping_respects_words_per_group_and_sentences() -> None:
    words = make_words("jedna dva tři čtyři pět. šest sedm osm devět deset jedenáct")
    style = resolve_style("bold-pop", {"words_per_group": 3})
    groups = group_words(words, style, 1080, 1920)
    assert all(1 <= len(g.words) <= 3 for g in groups)
    assert groups[1].words[-1]["w"] == "pět."  # sentence end closes a group
    for a, b in itertools.pairwise(groups):
        assert a.end <= b.start + 1e-6


def test_karaoke_uses_kf_tags() -> None:
    doc = build_ass(make_words("Ahoj jak se máš dnes"), resolve_style("karaoke"), 1080, 1920)
    assert "\\kf" in doc


def test_active_word_highlight_and_pop() -> None:
    style = resolve_style("bold-pop")
    evs = caption_events(make_words("jedna dva tři"), style, 1080, 1920, [])
    assert len(evs) == 3  # one event per active word
    hl = captions.ass_rgb(style["highlight_color"])
    assert hl in evs[1]["text"] and "\\t(0,120" in evs[1]["text"]


def test_typewriter_hides_future_words() -> None:
    evs = caption_events(make_words("jedna dva tři"), resolve_style("typewriter"), 1080, 1920, [])
    assert "\\alpha&HFF&" in evs[0]["text"]


def test_gradient_colors_per_char() -> None:
    evs = caption_events(make_words("ahoj"), resolve_style("gradient"), 1080, 1920, [])
    assert evs[0]["text"].count("\\1c") >= 4


def test_escape_braces() -> None:
    doc = build_ass(make_words("text {s} \\N backslash"), resolve_style("minimal"), 1080, 1920)
    events = [line for line in doc.splitlines() if line.startswith("Dialogue")]
    assert all("{s}" not in e for e in events)


def test_ass_helpers() -> None:
    assert ass_color("#FFD400") == "&H0000D4FF"
    assert ass_color("#000000", 0.6) == "&H66000000"
    assert ass_time(3661.239) == "1:01:01.24"


def test_keyword_match_czech_inflection() -> None:
    assert keyword_match("penězích", ["peníze"]) is False or keyword_match("penězi", ["peněz"])
    assert keyword_match("investice,", ["investice"])
    assert keyword_match("investicemi", ["investice"])
    assert not keyword_match("a", ["a"])


def test_word_edits_keep_timing() -> None:
    words = make_words("Ahoj svete dnes")
    out = apply_word_edits(words, {"1": "světe"})
    assert out[1]["t"] == "světe" and out[1]["s"] == words[1]["s"]
    doc = build_ass(out, resolve_style("minimal"), 1080, 1920)
    assert "světe" in doc and "svete" not in doc


def test_filler_removal_and_timemap() -> None:
    words = make_words("Takže ehm, jako, já si myslím, že prostě peníze nejsou vše.")
    lang = "cs"
    assert is_filler(words, 1, lang)  # ehm,
    assert is_filler(words, 2, lang)  # jako, (flanked by commas)
    tm, kept = build_timemap(words, 0, words[-1]["e"] + 0.2, remove_fillers=True, lang=lang)
    texts = [w["w"] for w in kept]
    assert "ehm," not in texts and "jako," not in texts
    assert not tm.trivial and tm.duration < words[-1]["e"] + 0.2
    mapped = map_words(kept, tm)
    assert all(b["s"] >= a["s"] for a, b in itertools.pairwise(mapped))
    assert mapped[-1]["e"] <= tm.duration + 1e-6


def test_silence_removal() -> None:
    words = make_words("jedna dva")
    words[1]["s"] += 3.0
    words[1]["e"] += 3.0
    tm, _ = build_timemap(words, 0, words[1]["e"], remove_silence=True)
    assert tm.duration < words[1]["e"] - 2.5


def test_emoji_events() -> None:
    style = resolve_style("emoji")
    evs = captions.emoji_events(make_words("Mluvíme o penězích a investicích."), style, 1080, 1920,
                                [{"word": "investicích", "emoji": "📈"}], "cs")
    assert evs and evs[0]["emoji"] in ("📈", "💰")
