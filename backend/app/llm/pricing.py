"""Token prices (USD per 1M tokens) and cost estimates.

Source: Anthropic pricing (checked 2026-11). Update when prices change.
"""

from __future__ import annotations

from typing import Any

PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}

# Heuristics for an hour of speech (~9 000 words). Czech tokenises worse than English.
WORDS_PER_HOUR = 9000
TOKENS_PER_WORD = {"cs": 2.3, "en": 1.4}
OUTPUT_TOKENS_PER_WINDOW = 3500  # JSON for ~5 clips + adaptive thinking
SYSTEM_TOKENS = 1100


def cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    p = PRICES.get(model)
    if not p:
        return None
    return input_tokens / 1e6 * p[0] + output_tokens / 1e6 * p[1]


def estimate_hour(model: str, language: str = "cs", window_min: float = 12.0, overlap_min: float = 1.5) -> dict[str, Any]:
    tpw = TOKENS_PER_WORD.get(language, 1.8)
    windows = 60.0 / max(1.0, window_min - overlap_min)
    transcript_tokens = WORDS_PER_HOUR * tpw * 1.25 * (window_min / max(1.0, window_min - overlap_min))
    inp = int(transcript_tokens + windows * SYSTEM_TOKENS)
    out = int(windows * OUTPUT_TOKENS_PER_WINDOW)
    c = cost(model, inp, out)
    return {"input_tokens": inp, "output_tokens": out, "usd": round(c, 4) if c is not None else None}
