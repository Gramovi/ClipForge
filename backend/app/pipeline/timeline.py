"""Clip timeline: silence / filler-word removal and source->output time mapping."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import Any

Word = dict[str, Any]

# Always removed when they stand alone (hesitations).
HARD_FILLERS = {
    "cs": {"ehm", "hm", "hmm", "eh", "em", "ehh", "mhm", "éé", "ee", "eee", "ééé", "mmm", "hmmm", "ehmm"},
    "en": {"um", "uh", "uhm", "erm", "er", "hmm", "hm", "mm", "mmm", "ah", "eh"},
}
# Removed only when they look like fillers (flanked by commas or pauses).
SOFT_FILLERS = {
    "cs": {"jako", "prostě", "vlastně", "jakoby", "takže", "tak", "no", "teda"},
    "en": {"like", "basically", "actually", "literally", "so", "well"},
}
_PUNCT = re.compile(r"^[\W_]+|[\W_]+$")

SILENCE_MIN_GAP = 0.45  # gaps longer than this are shortened
SILENCE_KEEP = 0.16  # how much of a removed gap to keep (natural breath)


def norm_word(w: str) -> str:
    return _PUNCT.sub("", w.lower())


def is_filler(words: list[Word], i: int, lang: str) -> bool:
    w = norm_word(words[i]["w"])
    if not w:
        return False
    hard = HARD_FILLERS.get(lang, set()) | HARD_FILLERS["en"]
    if w in hard:
        return True
    soft = SOFT_FILLERS.get(lang, set())
    if w not in soft:
        return False
    raw = words[i]["w"]
    prev_comma = i > 0 and words[i - 1]["w"].rstrip().endswith(",")
    own_comma = raw.rstrip().endswith(",")
    gap_before = i > 0 and float(words[i]["s"]) - float(words[i - 1]["e"]) > 0.25
    gap_after = i + 1 < len(words) and float(words[i + 1]["s"]) - float(words[i]["e"]) > 0.25
    repeated = i > 0 and norm_word(words[i - 1]["w"]) == w
    isolated_before = prev_comma or gap_before
    isolated_after = own_comma or gap_after
    return repeated or (isolated_before and isolated_after)


@dataclass
class TimeMap:
    """Ordered kept segments (source seconds)."""

    segments: list[tuple[float, float]]

    def __post_init__(self) -> None:
        self._cum: list[float] = []
        acc = 0.0
        for s, e in self.segments:
            self._cum.append(acc)
            acc += e - s
        self.duration = acc
        self._starts = [s for s, _ in self.segments]

    def to_output(self, t: float) -> float | None:
        """Map a source time to output time; None if inside a removed part."""
        i = bisect_right(self._starts, t) - 1
        if i < 0:
            return None
        s, e = self.segments[i]
        if t > e + 1e-6:
            return None
        return self._cum[i] + (t - s)

    def clamp_output(self, t: float) -> float:
        """Map a source time, snapping times inside removed parts to the next kept segment."""
        m = self.to_output(t)
        if m is not None:
            return m
        i = bisect_right(self._starts, t)
        if i >= len(self.segments):
            return self.duration
        return self._cum[i]

    @property
    def trivial(self) -> bool:
        return len(self.segments) <= 1


def build_timemap(
    words: list[Word],
    start: float,
    end: float,
    *,
    remove_silence: bool = False,
    remove_fillers: bool = False,
    lang: str = "cs",
) -> tuple[TimeMap, list[Word]]:
    """Return the time map and the words that remain (still in *source* time)."""
    clip_words = [w for w in words if float(w["e"]) > start and float(w["s"]) < end]
    if not remove_silence and not remove_fillers:
        return TimeMap([(start, end)]), clip_words

    kept_words: list[Word] = []
    cuts: list[tuple[float, float]] = []
    for i, w in enumerate(clip_words):
        if remove_fillers and is_filler(clip_words, i, lang):
            prev_e = float(clip_words[i - 1]["e"]) if i > 0 else start
            cuts.append((max(prev_e, float(w["s"]) - 0.02), float(w["e"])))
            continue
        kept_words.append(w)
    if remove_silence:
        prev = start
        for w in kept_words:
            ws = float(w["s"])
            if ws - prev > SILENCE_MIN_GAP:
                half = SILENCE_KEEP / 2
                cuts.append((prev + half, ws - half))
            prev = max(prev, float(w["e"]))
        if end - prev > SILENCE_MIN_GAP + 0.3:
            cuts.append((prev + 0.3, end))
    # merge cuts and invert to keep-segments
    cuts = sorted((max(start, a), min(end, b)) for a, b in cuts if b - a > 0.04)
    merged: list[tuple[float, float]] = []
    for a, b in cuts:
        if merged and a <= merged[-1][1] + 0.01:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    segs: list[tuple[float, float]] = []
    cur = start
    for a, b in merged:
        if a - cur > 0.08:
            segs.append((round(cur, 3), round(a, 3)))
        cur = max(cur, b)
    if end - cur > 0.08:
        segs.append((round(cur, 3), round(end, 3)))
    if not segs:
        segs = [(start, end)]
    return TimeMap(segs), kept_words


def map_words(words: list[Word], tm: TimeMap) -> list[Word]:
    """Copy words with times mapped to the output timeline (dropping words fully removed)."""
    out: list[Word] = []
    for w in words:
        s = tm.to_output(float(w["s"]))
        e = tm.to_output(float(w["e"]))
        if s is None and e is None:
            mid = tm.to_output((float(w["s"]) + float(w["e"])) / 2)
            if mid is None:
                continue
        s2 = tm.clamp_output(float(w["s"])) if s is None else s
        e2 = tm.clamp_output(float(w["e"])) if e is None else e
        if e2 - s2 < 0.04:
            e2 = s2 + 0.04
        out.append({**w, "s": round(s2, 3), "e": round(min(e2, tm.duration), 3)})
    return out
