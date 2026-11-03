"""Transcript windows and clip post-processing (pure functions, unit-tested).

Words are dicts ``{"w": text, "s": start, "e": end}`` with absolute times in seconds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

Word = dict[str, Any]

# Clip length presets: id -> (min seconds, max seconds, ideal seconds)
LENGTH_RANGES: dict[str, tuple[float, float, float]] = {
    "auto": (15.0, 90.0, 45.0),
    "lt30": (8.0, 30.0, 22.0),
    "30-60": (30.0, 60.0, 45.0),
    "60-90": (60.0, 90.0, 75.0),
    "90-180": (90.0, 180.0, 120.0),
}

_SENT_END = re.compile(r"[.!?…]+[\"'”“»)]*$")
SENTENCE_GAP = 0.8  # a pause this long also counts as a sentence boundary
START_PAD = 0.12
END_PAD = 0.30


@dataclass
class Window:
    index: int
    i0: int  # first word index (inclusive)
    i1: int  # last word index (inclusive)
    start: float
    end: float


@dataclass
class ClipCandidate:
    start: float
    end: float
    title: str
    hook: str = ""
    reason: str = ""
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    emojis: list[dict[str, str]] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    virality_score: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start


# ---------------------------------------------------------------------------
# sentence structure
# ---------------------------------------------------------------------------

def is_sentence_end(words: list[Word], i: int) -> bool:
    if i >= len(words) - 1:
        return True
    if _SENT_END.search(words[i]["w"]):
        return True
    return float(words[i + 1]["s"]) - float(words[i]["e"]) >= SENTENCE_GAP


def sentence_spans(words: list[Word]) -> list[tuple[int, int]]:
    """List of (first_word_idx, last_word_idx) for each sentence."""
    spans: list[tuple[int, int]] = []
    start = 0
    for i in range(len(words)):
        if is_sentence_end(words, i):
            spans.append((start, i))
            start = i + 1
    return spans


# ---------------------------------------------------------------------------
# windows
# ---------------------------------------------------------------------------

def split_windows(words: list[Word], window_s: float = 720.0, overlap_s: float = 90.0) -> list[Window]:
    """Split the transcript into overlapping windows aligned to sentence boundaries."""
    if not words:
        return []
    if overlap_s >= window_s:
        raise ValueError("overlap must be shorter than window")
    spans = sentence_spans(words)
    t0, t_end = float(words[0]["s"]), float(words[-1]["e"])
    windows: list[Window] = []
    w_start = t0
    while True:
        w_end_target = w_start + window_s
        # sentences whose start lies inside [w_start, w_end_target)
        inside = [sp for sp in spans if w_start <= float(words[sp[0]]["s"]) < w_end_target]
        if not inside:
            nxt = [sp for sp in spans if float(words[sp[0]]["s"]) >= w_start]
            if not nxt:
                break
            inside = [nxt[0]]
        i0, i1 = inside[0][0], inside[-1][1]
        windows.append(Window(len(windows), i0, i1, float(words[i0]["s"]), float(words[i1]["e"])))
        if i1 >= len(words) - 1 or w_end_target >= t_end:
            break
        w_start = max(float(words[i0]["s"]) + 1.0, w_end_target - overlap_s)
    return windows


def format_window(words: list[Word], window: Window, max_sentence_words: int = 40) -> str:
    """Render a window as timestamped lines for the LLM: ``[12.34-15.80] text``."""
    lines: list[str] = []
    sub = words[window.i0 : window.i1 + 1]
    for a, b in sentence_spans(sub):
        # break very long run-on "sentences" so timestamps stay precise
        for c in range(a, b + 1, max_sentence_words):
            d = min(b, c + max_sentence_words - 1)
            text = " ".join(w["w"] for w in sub[c : d + 1])
            lines.append(f"[{float(sub[c]['s']):.2f}-{float(sub[d]['e']):.2f}] {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# alignment
# ---------------------------------------------------------------------------

def _word_at_or_after(words: list[Word], t: float) -> int:
    for i, w in enumerate(words):
        if float(w["e"]) > t:
            return i
    return len(words) - 1


def _word_at_or_before(words: list[Word], t: float) -> int:
    for i in range(len(words) - 1, -1, -1):
        if float(words[i]["s"]) < t:
            return i
    return 0


def align_clip(
    words: list[Word],
    start: float,
    end: float,
    min_len: float,
    max_len: float,
    snap_window: float = 6.0,
    bounds: tuple[float, float] | None = None,
) -> tuple[float, float] | None:
    """Snap a clip to sentence boundaries and enforce its length.

    Returns ``(start, end)`` in seconds including a small padding, or ``None`` when no
    acceptable clip can be formed.
    """
    if not words or end <= start:
        return None
    lo_bound = bounds[0] if bounds else float("-inf")
    hi_bound = bounds[1] if bounds else float("inf")
    sent_starts = [0] + [i + 1 for i in range(len(words) - 1) if is_sentence_end(words, i)]
    sent_ends = [i for i in range(len(words)) if is_sentence_end(words, i)]

    wi_start = _word_at_or_after(words, start)
    wi_end = _word_at_or_before(words, end)
    if wi_end < wi_start:
        return None

    # --- snap start: prefer a sentence start at/just before, else just after
    t_s = float(words[wi_start]["s"])
    before = [i for i in sent_starts if i <= wi_start and t_s - float(words[i]["s"]) <= snap_window]
    after = [i for i in sent_starts if i > wi_start and float(words[i]["s"]) - t_s <= snap_window / 2]
    if before:
        si = before[-1]
    elif after:
        si = after[0]
    else:
        si = wi_start
    # --- snap end: prefer a sentence end at/just after, else just before
    t_e = float(words[wi_end]["e"])
    after_e = [i for i in sent_ends if i >= wi_end and float(words[i]["e"]) - t_e <= snap_window]
    before_e = [i for i in sent_ends if i < wi_end and t_e - float(words[i]["e"]) <= snap_window / 2 and i >= si]
    if after_e:
        ei = after_e[0]
    elif before_e:
        ei = before_e[-1]
    else:
        ei = wi_end

    def dur(a: int, b: int) -> float:
        return float(words[b]["e"]) - float(words[a]["s"])

    # --- too long: cut back to the last sentence end that fits, else last word that fits
    if dur(si, ei) > max_len:
        fitting = [i for i in sent_ends if si <= i <= ei and dur(si, i) <= max_len and dur(si, i) >= min_len]
        if fitting:
            ei = fitting[-1]
        else:
            fitting_w = [i for i in range(si, ei + 1) if dur(si, i) <= max_len]
            if not fitting_w:
                return None
            ei = fitting_w[-1]
    # --- too short: extend forward by sentences, then backward
    if dur(si, ei) < min_len:
        for i in sent_ends:
            if i > ei and float(words[i]["e"]) <= hi_bound and dur(si, i) <= max_len:
                ei = i
                if dur(si, ei) >= min_len:
                    break
    if dur(si, ei) < min_len:
        for i in reversed(sent_starts):
            if i < si and float(words[i]["s"]) >= lo_bound and dur(i, ei) <= max_len:
                si = i
                if dur(si, ei) >= min_len:
                    break
    if dur(si, ei) < min_len * 0.8:
        return None

    prev_end = float(words[si - 1]["e"]) if si > 0 else float("-inf")
    next_start = float(words[ei + 1]["s"]) if ei + 1 < len(words) else float("inf")
    s = max(float(words[si]["s"]) - START_PAD, (prev_end + float(words[si]["s"])) / 2, lo_bound, 0.0)
    e = min(float(words[ei]["e"]) + END_PAD, (next_start + float(words[ei]["e"])) / 2, hi_bound)
    return round(s, 3), round(e, 3)


# ---------------------------------------------------------------------------
# dedupe + ranking
# ---------------------------------------------------------------------------

def overlap_ratio(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Overlap as fraction of the shorter interval."""
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    shorter = max(1e-6, min(a[1] - a[0], b[1] - b[0]))
    return inter / shorter


def dedupe(clips: list[ClipCandidate], max_overlap: float = 0.5) -> list[ClipCandidate]:
    kept: list[ClipCandidate] = []
    for c in sorted(clips, key=lambda c: c.virality_score, reverse=True):
        overlapping = any(overlap_ratio((c.start, c.end), (k.start, k.end)) > max_overlap for k in kept)
        # also drop near-identical titles (same moment found twice with slightly different bounds)
        same_title = any(_norm(c.title) == _norm(k.title) and abs(c.start - k.start) < 30 for k in kept)
        if not overlapping and not same_title:
            kept.append(c)
    return kept


def _norm(s: str) -> str:
    return re.sub(r"\W+", "", s.lower())


def clamp_score(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if 0 < f <= 1.0:  # model answered on 0..1 scale
        f *= 100
    elif 1.0 < f <= 10.0:  # 0..10 scale
        f *= 10
    return round(max(0.0, min(100.0, f)), 1)


def compute_virality(scores: dict[str, float], model_score: float | None) -> float:
    """Blend the model's overall score with the weighted sub-scores (robust to bad model math)."""
    weighted = (
        0.35 * scores.get("hook", 0) + 0.2 * scores.get("flow", 0)
        + 0.3 * scores.get("value", 0) + 0.15 * scores.get("trend", 0)
    )
    if model_score is None or model_score <= 0:
        return round(weighted, 1)
    return round(0.5 * model_score + 0.5 * weighted, 1)


def finalize(
    words: list[Word],
    candidates: list[ClipCandidate],
    length: str,
    bounds: tuple[float, float] | None = None,
) -> list[ClipCandidate]:
    """Align, enforce length, dedupe and sort candidates."""
    min_len, max_len, _ = LENGTH_RANGES.get(length, LENGTH_RANGES["auto"])
    out: list[ClipCandidate] = []
    for c in candidates:
        if bounds and (c.end <= bounds[0] or c.start >= bounds[1]):
            continue
        aligned = align_clip(words, c.start, c.end, min_len, max_len, bounds=bounds)
        if not aligned:
            continue
        c.start, c.end = aligned
        out.append(c)
    return sorted(dedupe(out), key=lambda c: c.virality_score, reverse=True)


def words_in(words: list[Word], start: float, end: float) -> list[Word]:
    return [w for w in words if float(w["e"]) > start and float(w["s"]) < end]
