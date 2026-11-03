"""Speech-to-text with faster-whisper (word-level timestamps)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)

# Models that are good enough for Czech. Smaller ones work, but with noticeably worse accuracy.
RECOMMENDED_CZECH = ("large-v3", "large-v3-turbo")
WHISPER_MODELS: list[dict[str, str]] = [
    {"id": "large-v3", "label": "large-v3 – nejlepší přesnost (doporučeno pro češtinu)", "warning": ""},
    {"id": "large-v3-turbo", "label": "large-v3-turbo – rychlejší, téměř stejná kvalita", "warning": ""},
    {"id": "medium", "label": "medium – pro CPU", "warning": "V češtině výrazně více chyb než large-v3."},
    {"id": "small", "label": "small – rychlé, pro CPU", "warning": "V češtině hodně chyb, vhodné jen pro test."},
    {"id": "base", "label": "base – jen pro testování", "warning": "Nízká přesnost, pro češtinu nevhodné."},
]

LANGUAGES: dict[str, str] = {
    "auto": "Automaticky",
    "cs": "Čeština",
    "sk": "Slovenština",
    "en": "Angličtina",
    "de": "Němčina",
    "pl": "Polština",
    "es": "Španělština",
    "fr": "Francouzština",
    "it": "Italština",
    "pt": "Portugalština",
    "uk": "Ukrajinština",
    "ru": "Ruština",
    "hu": "Maďarština",
    "nl": "Nizozemština",
}


class NoSpeechError(RuntimeError):
    pass


_model_cache: dict[tuple[str, str, str], Any] = {}
_model_lock = threading.Lock()


def _resolve_device() -> tuple[str, str]:
    s = get_settings()
    device = s.whisper_device
    if device == "auto":
        try:
            import ctranslate2

            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:  # pragma: no cover - depends on host
            device = "cpu"
    compute = s.whisper_compute_type
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return device, compute


def load_model(name: str) -> Any:
    from faster_whisper import WhisperModel

    s = get_settings()
    device, compute = _resolve_device()
    key = (name, device, compute)
    with _model_lock:
        if key not in _model_cache:
            log.info("Loading Whisper model %s on %s (%s)", name, device, compute)
            _model_cache.clear()  # keep at most one model in memory
            _model_cache[key] = WhisperModel(
                name,
                device=device,
                compute_type=compute,
                cpu_threads=s.whisper_cpu_threads,
                download_root=str(s.whisper_models_dir) if s.whisper_models_dir else None,
            )
        return _model_cache[key]


def transcribe(
    wav_path: str,
    *,
    model_name: str,
    language: str | None,
    offset: float,
    duration: float,
    on_progress: Callable[[float], None] | None = None,
    initial_prompt: str | None = None,
) -> dict[str, Any]:
    """Transcribe *wav_path*; returned times are absolute (``offset`` added)."""
    model = load_model(model_name)
    s = get_settings()
    segments_iter, info = model.transcribe(
        wav_path,
        language=None if language in (None, "", "auto") else language,
        word_timestamps=True,
        beam_size=s.whisper_beam_size,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 700},
        condition_on_previous_text=False,
        initial_prompt=initial_prompt,
    )
    words: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    for seg in segments_iter:
        first = len(words)
        for w in seg.words or []:
            text = w.word.strip()
            if not text:
                continue
            words.append({
                "w": text,
                "s": round(offset + float(w.start), 3),
                "e": round(offset + float(max(w.end, w.start + 0.05)), 3),
                "p": round(float(w.probability), 3),
            })
        if len(words) > first:
            segments.append({
                "s": words[first]["s"],
                "e": words[-1]["e"],
                "text": seg.text.strip(),
                "wi": [first, len(words) - 1],
            })
        if on_progress and duration > 0:
            on_progress(min(1.0, float(seg.end) / duration))
    if not words:
        raise NoSpeechError("Ve videu nebyla rozpoznána žádná řeč.")
    return {
        "language": info.language,
        "language_probability": round(float(info.language_probability), 3),
        "model": model_name,
        "offset": offset,
        "words": words,
        "segments": segments,
    }
