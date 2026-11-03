"""Caption layout, ASS (libass) generation and SRT export.

The grouping/positioning logic here is mirrored 1:1 in ``frontend/src/lib/captions.ts`` so the
browser preview matches the final render. Keep them in sync.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.pipeline.emoji import emoji_for_words
from app.pipeline.presets import font_by_id, load_presets_file
from app.pipeline.timeline import norm_word

Word = dict[str, Any]
Style = dict[str, Any]

GROUP_PAUSE = 0.6  # a pause longer than this starts a new caption group
GROUP_TAIL = 0.5  # how long a group stays after its last word
GROUP_BRIDGE = 0.6  # bridge gaps shorter than this to avoid flicker
_SENT_PUNCT = re.compile(r"[.!?…]$")

# Vertical anchor (fraction of height) per aspect family and position
ANCHORS = {
    "portrait": {"top": 0.20, "middle": 0.50, "bottom": 0.72},
    "square": {"top": 0.14, "middle": 0.50, "bottom": 0.80},
    "landscape": {"top": 0.12, "middle": 0.50, "bottom": 0.86},
}


@dataclass
class Group:
    words: list[Word]
    start: float
    end: float


def aspect_family(w: int, h: int) -> str:
    r = w / h
    if r < 0.9:
        return "portrait"
    if r > 1.1:
        return "landscape"
    return "square"


def scale_factor(w: int, h: int) -> float:
    return min(w, h) / 1080.0


def display_text(word: Word, style: Style) -> str:
    t = str(word.get("t", word["w"]))
    return t.upper() if style.get("uppercase") else t


def max_chars_per_group(style: Style, w: int, h: int) -> int:
    px = float(style["font_size"]) * scale_factor(w, h)
    avg_char = px * 0.62 + float(style.get("letter_spacing", 0)) * scale_factor(w, h)
    return max(8, int((w * 0.86) / max(1.0, avg_char)))


def group_words(words: list[Word], style: Style, w: int, h: int) -> list[Group]:
    """Split words into on-screen groups (1-4 words). Mirrored in captions.ts."""
    n = int(style["words_per_group"])
    max_chars = max_chars_per_group(style, w, h)
    groups: list[list[Word]] = []
    cur: list[Word] = []

    def length(ws: list[Word]) -> int:
        return sum(len(display_text(x, style)) for x in ws) + max(0, len(ws) - 1)

    for word in words:
        if not display_text(word, style).strip():
            continue
        if cur and (
            len(cur) >= n
            or float(word["s"]) - float(cur[-1]["e"]) > GROUP_PAUSE
            or length([*cur, word]) > max_chars
        ):
            groups.append(cur)
            cur = []
        cur.append(word)
        if _SENT_PUNCT.search(str(word["w"])):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    out: list[Group] = []
    for i, g in enumerate(groups):
        start = float(g[0]["s"])
        end = float(g[-1]["e"]) + GROUP_TAIL
        if i + 1 < len(groups):
            nxt = float(groups[i + 1][0]["s"])
            if nxt - float(g[-1]["e"]) < GROUP_BRIDGE:
                end = nxt
            end = min(end, nxt)
        out.append(Group(g, round(start, 3), round(max(end, float(g[-1]["e"])), 3)))
    return out


# ---------------------------------------------------------------------------
# ASS helpers
# ---------------------------------------------------------------------------

def ass_color(hex_color: str, alpha: float = 1.0) -> str:
    """#RRGGBB + opacity -> &HAABBGGRR."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = round((1 - max(0.0, min(1.0, alpha))) * 255)
    return f"&H{a:02X}{b}{g}{r}".upper()


def ass_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def ass_alpha(opacity: float) -> str:
    return f"&H{round((1 - max(0.0, min(1.0, opacity))) * 255):02X}&"


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "⧵").replace("{", "(").replace("}", ")").replace("\n", " ")


def _lerp_color(a: str, b: str, t: float) -> str:
    ca = [int(a.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    c = [round(x + (y - x) * t) for x, y in zip(ca, cb, strict=True)]
    return "#{:02X}{:02X}{:02X}".format(*c)


def keyword_match(word: str, keywords: list[str]) -> bool:
    """Inflection-tolerant match (Czech): compare a stem prefix."""
    w = norm_word(word)
    if len(w) < 3:
        return False
    for k in keywords:
        for part in norm_word(k).split():
            if len(part) < 3:
                continue
            stem = part[: max(4, len(part) - 2)] if len(part) > 4 else part
            if w == part or w.startswith(stem):
                return True
    return False


def anchor_y(style: Style, w: int, h: int) -> float:
    fam = aspect_family(w, h)
    return h * (ANCHORS[fam][style["position"]] + float(style.get("offset_y", 0)) / 100.0)


# ---------------------------------------------------------------------------
# ASS document
# ---------------------------------------------------------------------------

def _style_line(name: str, family: str, size: float, bold: bool, primary: str, secondary: str,
                outline_c: str, back_c: str, border_style: int, outline: float, shadow: float,
                spacing: float = 0.0) -> str:
    return (
        f"Style: {name},{family},{size:.0f},{primary},{secondary},{outline_c},{back_c},"
        f"{-1 if bold else 0},0,0,0,100,100,{spacing:.1f},0,{border_style},{outline:.1f},{shadow:.1f},5,40,40,40,1"
    )


def build_ass(
    words: list[Word],
    style: Style,
    width: int,
    height: int,
    *,
    keywords: list[str] | None = None,
    hook_text: str | None = None,
    user_fonts: dict[str, dict[str, Any]] | None = None,
    duration: float | None = None,
) -> str:
    """Build a complete .ass document. *words* must be in output time (seconds from clip start)."""
    sc = scale_factor(width, height)
    font = font_by_id(style["font"], user_fonts)
    size = float(style["font_size"]) * sc
    bold = int(font.get("weight", 700)) >= 700
    bg = style.get("background") or {}
    box = bool(bg.get("enabled"))
    outline_w = float(style["outline_width"]) * sc
    shadow = float(style["shadow_depth"]) * sc
    border_style = 3 if box else 1
    outline_c = ass_color(bg.get("color", "#000000"), float(bg.get("opacity", 0.6))) if box else ass_color(style["outline_color"])
    box_pad = float(bg.get("padding", 16)) * sc
    back_c = ass_color(style["shadow_color"], float(style["shadow_opacity"]))
    spacing = float(style.get("letter_spacing", 0)) * sc

    hook_cfg = load_presets_file()["hook"]
    hook_font = font_by_id(hook_cfg["font"], user_fonts)

    lines = [
        "[Script Info]",
        "; Generated by ClipForge",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line("Caption", font["family"], size, bold, ass_color(style["text_color"]),
                    ass_color(style["text_color"]), outline_c, back_c, border_style,
                    box_pad if box else outline_w, 0 if box else shadow, spacing),
        _style_line("Hook", hook_font["family"], float(hook_cfg["font_size"]) * sc,
                    int(hook_font.get("weight", 700)) >= 700, ass_color(hook_cfg["text_color"]),
                    ass_color(hook_cfg["text_color"]),
                    ass_color(hook_cfg["background_color"], float(hook_cfg["background_opacity"])),
                    ass_color("#000000", 0.0), 3, 22 * sc, 0),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    x = width / 2
    y = anchor_y(style, width, height)
    events = caption_events(words, style, width, height, keywords or [])
    for ev in events:
        pos = f"\\an5\\pos({x:.0f},{y:.0f})"
        if style.get("rotation"):
            pos += f"\\frz{-float(style['rotation']):.1f}"
        glow = style.get("glow") or {}
        if glow.get("enabled") and not box:
            strength = float(glow.get("strength", 8)) * sc
            glow_tags = (
                f"{{{pos}\\bord{outline_w + strength:.1f}\\blur{strength:.1f}\\3c{ass_rgb(glow.get('color', '#00E5FF'))}"
                f"\\1a&HFF&\\shad0{ev['fade']}}}"
            )
            lines.append(f"Dialogue: 0,{ass_time(ev['start'])},{ass_time(ev['end'])},Caption,,0,0,0,,{glow_tags}{ev['plain']}")
        lines.append(
            f"Dialogue: 1,{ass_time(ev['start'])},{ass_time(ev['end'])},Caption,,0,0,0,,{{{pos}{ev['fade']}}}{ev['text']}"
        )
    if hook_text and hook_text.strip():
        hd = float(hook_cfg["duration"])
        if duration:
            hd = min(hd, duration)
        hy = height * float(hook_cfg["position_y"])
        txt = ass_escape(hook_text.strip())
        lines.append(
            f"Dialogue: 2,{ass_time(0)},{ass_time(hd)},Hook,,{int(width * 0.08)},{int(width * 0.08)},0,,"
            f"{{\\an5\\pos({x:.0f},{hy:.0f})\\fscx80\\fscy80\\t(0,160,\\fscx100\\fscy100)\\fad(120,200)}}{txt}"
        )
    return "\n".join(lines) + "\n"


def _word_runs(text: str, color: str, style: Style, idx_in_group: int, total_chars: int, offset: int) -> str:
    """Per-character gradient colouring (or a single colour)."""
    grad = style.get("gradient") or {}
    if not grad.get("enabled"):
        return f"{{\\1c{ass_rgb(color)}}}{ass_escape(text)}"
    out = []
    for i, ch in enumerate(text):
        t = (offset + i) / max(1, total_chars - 1)
        out.append(f"{{\\1c{ass_rgb(_lerp_color(grad['from'], grad['to'], t))}}}{ass_escape(ch)}")
    return "".join(out)


def caption_events(words: list[Word], style: Style, width: int, height: int, keywords: list[str]) -> list[dict[str, Any]]:
    """Return ASS events: {start, end, text, plain, fade}."""
    groups = group_words(words, style, width, height)
    mode = style["highlight_mode"]
    anim = style["animation"]
    act = float(style["active_scale"])
    events: list[dict[str, Any]] = []
    for g in groups:
        texts = [display_text(w, style) for w in g.words]
        plain = ass_escape(" ".join(texts))
        total_chars = sum(len(t) for t in texts) + len(texts) - 1
        if mode == "karaoke":
            parts = [f"{{\\1c{ass_rgb(style['highlight_color'])}\\2c{ass_rgb(style['text_color'])}}}"]
            cursor = g.start
            for i, w in enumerate(g.words):
                lead = max(0.0, float(w["s"]) - cursor)
                if lead > 0.01:
                    parts.append(f"{{\\k{round(lead * 100)}}}")
                nxt = float(g.words[i + 1]["s"]) if i + 1 < len(g.words) else float(w["e"])
                dur = max(0.05, nxt - float(w["s"]))
                sep = " " if i + 1 < len(g.words) else ""
                parts.append(f"{{\\kf{round(dur * 100)}}}{ass_escape(texts[i])}{sep}")
                cursor = float(w["s"]) + dur
            fade = "\\fad(80,80)"
            events.append({"start": g.start, "end": g.end, "text": "".join(parts), "plain": plain, "fade": fade})
            continue

        for k, active in enumerate(g.words):
            s = g.start if k == 0 else float(active["s"])
            e = g.end if k == len(g.words) - 1 else float(g.words[k + 1]["s"])
            if e - s < 0.02:
                continue
            pieces: list[str] = []
            char_off = 0
            for j, w in enumerate(g.words):
                t = texts[j]
                color = style["text_color"]
                is_kw = keyword_match(str(w["w"]), keywords)
                if mode == "keywords" and is_kw:
                    color = style["highlight_color"]
                if mode == "active_word" and j == k:
                    color = style["highlight_color"]
                seg = _word_runs(t, color, style, j, total_chars, char_off)
                tags = ""
                if j == k and anim in ("pop", "bounce") and mode != "none":
                    a = act * 100
                    if anim == "pop":
                        tags = f"{{\\fscx{a * 1.15:.0f}\\fscy{a * 1.15:.0f}\\t(0,120,\\fscx{a:.0f}\\fscy{a:.0f})}}"
                    else:
                        tags = (
                            f"{{\\fscx{a * 0.75:.0f}\\fscy{a * 0.75:.0f}\\t(0,90,\\fscx{a * 1.15:.0f}\\fscy{a * 1.15:.0f})"
                            f"\\t(90,180,\\fscx{a:.0f}\\fscy{a:.0f})}}"
                        )
                elif j == k and anim in ("pop", "bounce") and mode == "none" and act > 1.0:
                    tags = f"{{\\fscx{act * 100:.0f}\\fscy{act * 100:.0f}}}"
                if anim == "typewriter":
                    if j > k:
                        seg = f"{{\\alpha&HFF&}}{ass_escape(t)}"
                    elif j == k:
                        wd = max(0.05, min(float(w["e"]), e) - float(w["s"]))
                        base_ms = max(0.0, float(w["s"]) - s) * 1000
                        step = wd * 1000 / max(1, len(t))
                        seg = "".join(
                            f"{{\\1c{ass_rgb(color)}\\alpha&HFF&"
                            f"\\t({base_ms + i * step:.0f},{base_ms + i * step + 1:.0f},\\alpha&H00&)}}{ass_escape(ch)}"
                            for i, ch in enumerate(t)
                        )
                    else:
                        seg = f"{{\\alpha&H00&}}{seg}"
                reset = "{\\fscx100\\fscy100}" if tags else ""
                pieces.append(f"{tags}{seg}{reset}")
                char_off += len(t) + 1
            fade = ""
            if anim == "fade":
                fin = 150 if k == 0 else 0
                fout = 120 if k == len(g.words) - 1 else 0
                if fin or fout:
                    fade = f"\\fad({fin},{fout})"
            events.append({"start": s, "end": e, "text": " ".join(pieces), "plain": plain, "fade": fade})
    return events


def emoji_events(words: list[Word], style: Style, width: int, height: int,
                 emojis: list[dict[str, str]], lang: str) -> list[dict[str, Any]]:
    """Timed emoji overlays (rendered as PNG overlays, shown above the caption group)."""
    if not style.get("emoji"):
        return []
    groups = group_words(words, style, width, height)
    out: list[dict[str, Any]] = []
    last_end = -1.0
    for g in groups:
        found = emoji_for_words([str(w["w"]) for w in g.words], emojis, lang)
        if not found:
            continue
        idx, em = found
        s = float(g.words[idx]["s"])
        if s < last_end + 0.4:
            continue
        e = max(g.end, s + 0.9)
        out.append({"start": round(s, 3), "end": round(e, 3), "emoji": em})
        last_end = e
    return out


def emoji_geometry(style: Style, width: int, height: int) -> tuple[int, float, float]:
    """(size px, center x, center y) of emoji overlays - mirrored in captions.ts."""
    sc = scale_factor(width, height)
    size = int(float(style["font_size"]) * sc * 1.5)
    y = anchor_y(style, width, height) - float(style["font_size"]) * sc * 1.45
    return size, width / 2, y


# ---------------------------------------------------------------------------
# SRT / TXT
# ---------------------------------------------------------------------------

def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(words: list[Word], max_words: int = 7, max_chars: int = 42) -> str:
    """Readable SRT (longer lines than the on-screen groups). UTF-8 text."""
    cues: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        text = str(w.get("t", w["w"])).strip()
        if not text:
            continue
        if cur and (
            len(cur) >= max_words
            or float(w["s"]) - float(cur[-1]["e"]) > 0.8
            or len(" ".join(str(x.get("t", x["w"])) for x in [*cur, w])) > max_chars
        ):
            cues.append(cur)
            cur = []
        cur.append(w)
        if _SENT_PUNCT.search(text):
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)
    blocks = []
    for i, c in enumerate(cues, 1):
        text = " ".join(str(x.get("t", x["w"])).strip() for x in c)
        blocks.append(f"{i}\n{_srt_time(float(c[0]['s']))} --> {_srt_time(float(c[-1]['e']))}\n{text}\n")
    return "\n".join(blocks)


def apply_word_edits(words: list[Word], edits: dict[str, str] | None) -> list[Word]:
    """Apply text corrections keyed by global word index ("i") without changing timing."""
    if not edits:
        return words
    out = []
    for w in words:
        key = str(w.get("i"))
        if key in edits:
            out.append({**w, "t": edits[key]})
        else:
            out.append(w)
    return out
