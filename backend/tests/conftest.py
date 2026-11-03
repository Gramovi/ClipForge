from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="clipforge-test-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ.setdefault("DATA_DIR", str(_TMP / "data"))
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LLM_PROVIDER", "anthropic")
os.environ.setdefault("ANTHROPIC_API_KEY", "")


def make_words(text: str, start: float = 0.0, wdur: float = 0.3, gap: float = 0.1,
               sentence_pause: float = 0.0) -> list[dict[str, Any]]:
    """Build word dicts with synthetic timing from a text."""
    words = []
    t = start
    for i, w in enumerate(text.split()):
        words.append({"w": w, "s": round(t, 3), "e": round(t + wdur, 3), "i": i})
        t += wdur + gap
        if w[-1] in ".!?":
            t += sentence_pause
    return words


@pytest.fixture
def tmp_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)
