"""Emoji selection and rasterisation (libass cannot draw colour emoji, so we overlay PNGs)."""

from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.pipeline.timeline import norm_word


def _load_fallback() -> dict[str, str]:
    """Keyword stems -> emoji, shared with the browser preview (shared/emoji-keywords.json)."""
    with open(get_settings().shared_dir / "emoji-keywords.json", encoding="utf-8") as f:
        data: dict[str, str] = json.load(f)["stems"]
    return data


FALLBACK: dict[str, str] = _load_fallback()


def emoji_for_words(words: list[str], ai_emojis: list[dict[str, str]], lang: str) -> tuple[int, str] | None:
    """Return (word index, emoji) for the first word in the group that deserves an emoji."""
    ai = [(norm_word(e.get("word", "")), e.get("emoji", "")) for e in ai_emojis if e.get("emoji")]
    for i, raw in enumerate(words):
        w = norm_word(raw)
        if len(w) < 3:
            continue
        for k, em in ai:
            if k and (w == k or (len(k) >= 4 and w.startswith(k[: max(4, len(k) - 2)]))):
                return i, em
    for i, raw in enumerate(words):
        w = norm_word(raw)
        if len(w) < 2:
            continue
        for stem, em in FALLBACK.items():
            if (len(stem) <= 3 and w == stem) or (len(stem) > 3 and w.startswith(stem)):
                return i, em
    return None


@lru_cache
def emoji_font_path() -> str | None:
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", "Noto Color Emoji"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    p = out.stdout.strip()
    return p if p and "emoji" in p.lower() else None


def render_emoji_png(emoji: str, dst: Path, size: int) -> bool:
    """Rasterise an emoji to a transparent PNG. Returns False if no colour emoji font is available."""
    from PIL import Image, ImageDraw, ImageFont

    font_path = emoji_font_path()
    if not font_path:
        return False
    try:
        font = ImageFont.truetype(font_path, 109)  # Noto Color Emoji bitmap strike size
    except OSError:
        return False
    img = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((80, 80), emoji, font=font, embedded_color=True, anchor="mm")
    bbox = img.getbbox()
    if not bbox:
        return False
    img = img.crop(bbox)
    scale = size / max(img.width, img.height)
    img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.Resampling.LANCZOS)
    img.save(dst)
    return True
