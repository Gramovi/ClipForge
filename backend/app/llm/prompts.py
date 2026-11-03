"""Prompt + JSON schema for moment finding."""

from __future__ import annotations

from typing import Any

LANGUAGE_NAMES = {
    "cs": "Czech (čeština)", "sk": "Slovak", "en": "English", "de": "German", "pl": "Polish",
    "es": "Spanish", "fr": "French", "it": "Italian", "pt": "Portuguese", "uk": "Ukrainian",
    "ru": "Russian", "hu": "Hungarian", "nl": "Dutch",
}

CLIP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "reason": {"type": "string"},
                    "scores": {
                        "type": "object",
                        "properties": {
                            "hook": {"type": "number"},
                            "flow": {"type": "number"},
                            "value": {"type": "number"},
                            "trend": {"type": "number"},
                        },
                        "required": ["hook", "flow", "value", "trend"],
                        "additionalProperties": False,
                    },
                    "virality_score": {"type": "number"},
                    "description": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "emojis": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"word": {"type": "string"}, "emoji": {"type": "string"}},
                            "required": ["word", "emoji"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "start", "end", "title", "hook", "reason", "scores", "virality_score",
                    "description", "hashtags", "keywords", "emojis",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a senior short-form video editor. You find the moments in long-form \
videos (podcasts, interviews, streams) that will perform best as standalone TikTok / Reels / Shorts clips.

What makes a great clip:
- A strong HOOK in the first 1-3 seconds: a bold claim, a surprising fact, a question, conflict, \
emotion, or a punchline setup. The first sentence must grab attention on its own.
- It is SELF-CONTAINED: a viewer with no context understands it. It does not rely on "as I said before".
- It delivers something: a concrete tip, a story with a payoff, a strong opinion or controversy, \
humour, an emotional or vulnerable moment, a surprising insight.
- It NEVER starts or ends in the middle of a sentence. Start at the beginning of a sentence, end after \
a sentence that completes the thought (ideally on a punchline or conclusion).

Rules:
- Use ONLY timestamps that appear in the transcript lines ("[start-end] text"). The clip start must be \
the start time of a line, the clip end must be the end time of a line.
- Find ALL moments in the excerpt that are genuinely worth posting - do not stop after a few. \
A typical 12-minute excerpt of good conversation contains 3-8 strong clips. Do not invent weak clips \
just to fill a quota, and do not return overlapping duplicates of the same moment.
- Scores are integers 0-100: hook (strength of the first seconds), flow (coherent, self-contained, \
clean start/end), value (insight, entertainment or emotion delivered), trend (fit with what performs \
on social media now). virality_score is your overall 0-100 prediction. Be critical: average clips \
score 40-60, only exceptional ones exceed 85.
- title: catchy, max ~60 characters, no clickbait lies. hook: the opening line of the clip, quoted \
or lightly cleaned up. reason: 1-2 sentences why this clip could perform well. description: a ready \
social media caption (1-3 sentences). hashtags: 3-6 relevant hashtags including '#'. keywords: 2-6 \
important words that literally appear in the clip (for highlighting). emojis: 1-4 pairs of a word \
that appears in the clip and a fitting emoji.
- Output JSON only, matching the schema. If nothing is worth clipping, return {"clips": []}."""


def build_user_prompt(
    transcript: str,
    language: str,
    min_len: float,
    max_len: float,
    ideal_len: float,
    focus: str | None,
    window_info: str,
) -> str:
    lang = LANGUAGE_NAMES.get(language, language)
    parts = [
        f"Video language: {lang}. Write title, hook, reason, description, hashtags, keywords and emoji "
        f"words in {lang} - the same language as the video.",
        f"Clip length: each clip must be between {min_len:.0f} and {max_len:.0f} seconds long "
        f"(ideally about {ideal_len:.0f} s).",
    ]
    if focus:
        parts.append(
            "User focus: prioritise moments about the following topic / keywords. Only include other "
            f"moments if they are exceptional. Topic: {focus.strip()[:300]}"
        )
    parts.append(f"{window_info}\n\nTranscript:\n{transcript}")
    return "\n\n".join(parts)


REPAIR_PROMPT = """Your previous answer was not valid JSON for the required schema ({error}). \
Answer again with ONLY a JSON object of the form {{"clips": [ ... ]}} following all the rules."""
