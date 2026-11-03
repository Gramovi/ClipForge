"""Moment finding: transcript windows -> LLM -> validated, aligned clip candidates."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import Settings, get_settings
from app.llm import LLMConfigError, LLMError, LLMProvider, LLMRefusalError, LLMTransientError
from app.llm.jsonfix import JSONRepairError, parse_json_loose
from app.llm.pricing import cost
from app.llm.prompts import CLIP_SCHEMA, MORE_PROMPT, REPAIR_PROMPT, SYSTEM_PROMPT, build_user_prompt
from app.pipeline.moments import (
    LENGTH_RANGES,
    ClipCandidate,
    Window,
    Word,
    clamp_score,
    compute_virality,
    finalize,
    format_window,
    split_windows,
)

log = logging.getLogger(__name__)

LOCAL_MIN_CLIPS = 3  # ask local models for more moments when they return fewer
LOCAL_MAX_WINDOW_MIN = 6.0  # small local models handle shorter excerpts much better


class _Scores(BaseModel):
    hook: float = 0
    flow: float = 0
    value: float = 0
    trend: float = 0


class _Emoji(BaseModel):
    word: str
    emoji: str


class LLMClip(BaseModel):
    start: float
    end: float
    title: str = Field(min_length=1)
    hook: str = ""
    reason: str = ""
    scores: _Scores = Field(default_factory=_Scores)
    virality_score: float = 0
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    emojis: list[_Emoji] = Field(default_factory=list)

    @field_validator("hashtags", mode="before")
    @classmethod
    def _tags(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = v.replace(",", " ").split()
        out = []
        for t in v or []:
            t = str(t).strip().replace(" ", "")
            if t:
                out.append(t if t.startswith("#") else f"#{t}")
        return out[:8]

    @field_validator("keywords", mode="before")
    @classmethod
    def _kw(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",")]
        return [str(x).strip() for x in (v or []) if str(x).strip()][:8]


@dataclass
class FinderResult:
    candidates: list[ClipCandidate]
    input_tokens: int = 0
    output_tokens: int = 0
    windows: int = 0
    failed_windows: int = 0
    warnings: list[str] = field(default_factory=list)
    cost_usd: float | None = None


def parse_clips(text: str, window: Window) -> list[LLMClip]:
    """Parse model output into clips; raises JSONRepairError if unusable."""
    data = parse_json_loose(text)
    items: Any
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("clips")
        if items is None:  # some local models use another key, or return a single clip
            lists = [v for v in data.values() if isinstance(v, list)]
            items = lists[0] if lists else ([data] if "start" in data else None)
    else:
        items = None
    if not isinstance(items, list):
        raise JSONRepairError("chybí pole 'clips'")
    clips: list[LLMClip] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            clips.append(LLMClip.model_validate(raw))
        except ValidationError as e:
            log.debug("dropping invalid clip %s: %s", raw, e)
    if items and not clips:
        raise JSONRepairError("žádný klip neprošel validací schématu")
    # Some local models answer with times relative to the window start -> shift them.
    def inside(c: LLMClip, off: float = 0.0) -> bool:
        return window.start - 30 <= c.start + off <= window.end + 30 and c.end + off > c.start + off

    if clips and not any(inside(c) for c in clips) and all(inside(c, window.start) for c in clips):
        for c in clips:
            c.start += window.start
            c.end += window.start
    return [c for c in clips if inside(c)]


def _to_candidate(c: LLMClip) -> ClipCandidate:
    scores = {k: clamp_score(getattr(c.scores, k)) for k in ("hook", "flow", "value", "trend")}
    model_score = clamp_score(c.virality_score)
    return ClipCandidate(
        start=float(c.start),
        end=float(c.end),
        title=c.title.strip()[:200],
        hook=c.hook.strip(),
        reason=c.reason.strip(),
        description=c.description.strip(),
        hashtags=c.hashtags,
        keywords=c.keywords,
        emojis=[{"word": e.word, "emoji": e.emoji} for e in c.emojis][:6],
        scores=scores,
        virality_score=compute_virality(scores, model_score),
    )


def _call_window(
    provider: LLMProvider,
    words: list[Word],
    window: Window,
    total: int,
    language: str,
    length: str,
    focus: str | None,
    settings: Settings,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[ClipCandidate], int, int]:
    min_len, max_len, ideal = LENGTH_RANGES.get(length, LENGTH_RANGES["auto"])
    transcript = format_window(words, window)
    info = (
        f"This is excerpt {window.index + 1} of {total} "
        f"(from {window.start:.0f} s to {window.end:.0f} s of the video)."
    )
    base_prompt = build_user_prompt(transcript, language, min_len, max_len, ideal, focus, info)
    prompt = base_prompt
    in_tok = out_tok = 0
    last_err: Exception | None = None
    attempts = settings.llm_max_retries + (1 if provider.is_local else 0)
    for attempt in range(attempts):
        try:
            res = provider.complete_json(SYSTEM_PROMPT, prompt, CLIP_SCHEMA)
        except LLMTransientError as e:
            last_err = e
            delay = e.retry_after or min(60.0, 2.0 * (2**attempt)) + random.uniform(0, 1.5)
            log.warning("window %d transient error (%s), retry in %.1fs", window.index, e, delay)
            sleep(delay)
            continue
        in_tok += res.input_tokens
        out_tok += res.output_tokens
        try:
            clips = parse_clips(res.text, window)
        except JSONRepairError as e:
            last_err = e
            log.warning("window %d invalid JSON (%s), asking again", window.index, e)
            prompt = base_prompt + "\n\n" + REPAIR_PROMPT.format(error=str(e)[:200])
            continue
        result = [_to_candidate(c) for c in clips]
        if provider.is_local and len(result) < LOCAL_MIN_CLIPS:
            # small local models tend to stop after one or two moments -> ask once for more
            found = "\n".join(f"- [{c.start:.2f}-{c.end:.2f}] {c.title}" for c in result) or "- (none)"
            try:
                more = provider.complete_json(SYSTEM_PROMPT, base_prompt + "\n\n" + MORE_PROMPT.format(found=found), CLIP_SCHEMA)
                in_tok += more.input_tokens
                out_tok += more.output_tokens
                result += [_to_candidate(c) for c in parse_clips(more.text, window)]
            except (LLMTransientError, JSONRepairError) as e:
                log.info("window %d: follow-up request failed (%s), keeping first answer", window.index, e)
        return result, in_tok, out_tok
    raise LLMError(f"Okno {window.index + 1}: {last_err}")


def find_moments(
    words: list[Word],
    *,
    language: str,
    length: str,
    focus: str | None,
    provider: LLMProvider,
    bounds: tuple[float, float] | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    settings: Settings | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> FinderResult:
    s = settings or get_settings()
    win_min, overlap_min = s.llm_window_minutes, s.llm_window_overlap_minutes
    if provider.is_local and win_min > LOCAL_MAX_WINDOW_MIN:
        win_min, overlap_min = LOCAL_MAX_WINDOW_MIN, min(overlap_min, 1.0)
    windows = split_windows(words, win_min * 60, overlap_min * 60)
    result = FinderResult(candidates=[], windows=len(windows))
    if not windows:
        return result
    lock = threading.Lock()
    done = 0
    raw: list[ClipCandidate] = []
    workers = 1 if provider.is_local else max(1, s.llm_concurrency)
    errors: list[str] = []

    def job(w: Window) -> tuple[list[ClipCandidate], int, int]:
        return _call_window(provider, words, w, len(windows), language, length, focus, s, sleep)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(job, w): w for w in windows}
        for fut in as_completed(futures):
            w = futures[fut]
            try:
                clips, i, o = fut.result()
                raw.extend(clips)
                result.input_tokens += i
                result.output_tokens += o
            except LLMConfigError:
                for f in futures:
                    f.cancel()
                raise
            except LLMRefusalError as e:
                result.failed_windows += 1
                errors.append(f"okno {w.index + 1}: {e}")
            except LLMError as e:
                result.failed_windows += 1
                errors.append(str(e))
            with lock:
                done += 1
                if on_progress:
                    on_progress(done / len(windows), f"Analyzováno {done}/{len(windows)} částí")
    if result.failed_windows == len(windows):
        raise LLMError("AI model je nedostupný nebo opakovaně vrací chybné odpovědi. " + "; ".join(errors[:3]))
    if errors:
        result.warnings.append(f"{len(errors)} z {len(windows)} částí se nepodařilo analyzovat: " + "; ".join(errors[:3]))
    result.candidates = finalize(words, raw, length, bounds)
    result.cost_usd = cost(provider.model, result.input_tokens, result.output_tokens)
    return result
