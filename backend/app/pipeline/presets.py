"""Caption preset loading/merging (shared/caption-presets.json is the single source of truth)."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings

Style = dict[str, Any]


@lru_cache
def load_presets_file(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else get_settings().presets_file
    with open(p, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def deep_merge(base: dict[str, Any], over: dict[str, Any] | None) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


def builtin_ids() -> list[str]:
    return [p["id"] for p in load_presets_file()["presets"]]


def resolve_style(preset_id: str | None, overrides: dict[str, Any] | None = None,
                  user_presets: dict[str, dict[str, Any]] | None = None) -> Style:
    """defaults <- built-in preset <- (user preset) <- per-clip overrides."""
    data = load_presets_file()
    style = copy.deepcopy(data["defaults"])
    builtin = {p["id"]: p for p in data["presets"]}
    if user_presets and preset_id in user_presets:
        style = deep_merge(style, user_presets[preset_id])
    else:
        preset = builtin.get(preset_id or "", builtin["bold-pop"])
        style = deep_merge(style, preset["style"])
    style = deep_merge(style, overrides)
    return sanitize_style(style)


def _clamp(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, f))


def sanitize_style(style: Style) -> Style:
    s = style
    s["font_size"] = _clamp(s.get("font_size"), 20, 200, 78)
    s["outline_width"] = _clamp(s.get("outline_width"), 0, 20, 5)
    s["shadow_depth"] = _clamp(s.get("shadow_depth"), 0, 20, 3)
    s["shadow_opacity"] = _clamp(s.get("shadow_opacity"), 0, 1, 0.6)
    s["offset_y"] = _clamp(s.get("offset_y"), -40, 40, 0)
    s["words_per_group"] = int(_clamp(s.get("words_per_group"), 1, 4, 3))
    s["active_scale"] = _clamp(s.get("active_scale"), 1.0, 1.6, 1.1)
    s["letter_spacing"] = _clamp(s.get("letter_spacing"), -5, 20, 0)
    s["rotation"] = _clamp(s.get("rotation"), -15, 15, 0)
    if s.get("position") not in ("top", "middle", "bottom"):
        s["position"] = "bottom"
    if s.get("animation") not in ("none", "pop", "bounce", "fade", "typewriter"):
        s["animation"] = "pop"
    if s.get("highlight_mode") not in ("active_word", "karaoke", "keywords", "none"):
        s["highlight_mode"] = "active_word"
    for key in ("text_color", "highlight_color", "outline_color", "shadow_color"):
        s[key] = normalize_color(s.get(key), "#FFFFFF")
    return s


def normalize_color(v: Any, default: str) -> str:
    if not isinstance(v, str):
        return default
    v = v.strip()
    if not v.startswith("#"):
        v = "#" + v
    if len(v) == 4:
        v = "#" + "".join(c * 2 for c in v[1:])
    try:
        int(v[1:7], 16)
    except ValueError:
        return default
    return v[:7].upper() if len(v) >= 7 else default


def font_by_id(font_id: str, user_fonts: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    if user_fonts and font_id in user_fonts:
        return dict(user_fonts[font_id])
    fonts = {f["id"]: f for f in load_presets_file()["fonts"]}
    return dict(fonts.get(font_id) or fonts["montserrat-black"])
