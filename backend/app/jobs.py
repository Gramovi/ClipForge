"""Background jobs executed by the RQ worker. Never called inside HTTP requests."""

from __future__ import annotations

import json
import logging
import time
import traceback
import zipfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_sessionmaker
from app.llm import LLMConfigError, LLMError, get_provider
from app.models import Clip, ExportJob, Project
from app.pipeline import finder
from app.pipeline.media import MediaError, extract_audio, has_speech_energy, probe, thumbnail
from app.pipeline.moments import words_in
from app.pipeline.transcribe import NoSpeechError, transcribe
from app.services.clip_render import ensure_preview_and_analysis, render_clip
from app.storage import get_storage, project_prefix

log = logging.getLogger(__name__)

# (step id, weight) – weights sum to 100
STEPS: list[tuple[str, float]] = [
    ("upload", 4.0),
    ("transcribe", 40.0),
    ("moments", 21.0),
    ("reframe", 12.0),
    ("render", 23.0),
]


class Progress:
    """Throttled progress writer with a simple ETA."""

    def __init__(self, db: Session, project: Project) -> None:
        self.db = db
        self.project = project
        self.t0 = time.monotonic()
        self.last = 0.0
        self.weights = dict(STEPS)
        self.offsets: dict[str, float] = {}
        acc = 0.0
        for k, w in STEPS:
            self.offsets[k] = acc
            acc += w

    def set(self, step: str, frac: float, message: str | None = None, force: bool = False) -> None:
        now = time.monotonic()
        overall = self.offsets[step] + self.weights[step] * max(0.0, min(1.0, frac))
        p = self.project
        p.step = step
        p.step_progress = round(frac * 100, 1)
        p.progress = round(overall, 1)
        if message is not None:
            p.message = message
        elapsed = now - self.t0
        p.eta_seconds = round(elapsed / overall * (100 - overall), 0) if overall > 3 and elapsed > 5 else None
        if force or now - self.last > 1.0:
            self.db.commit()
            self.last = now


def _fail(db: Session, project: Project, message: str) -> None:
    project.status = "failed"
    project.error = message
    project.eta_seconds = None
    project.finished_at = datetime.now(UTC)
    db.commit()


def _download_url(db: Session, project: Project, prog: Progress) -> None:
    import yt_dlp

    st = get_storage()
    key = f"{project_prefix(project.user_id, project.id)}/source.%(ext)s"
    out_tmpl = str(st.local_path(key))
    max_bytes = get_settings().max_upload_bytes

    def hook(d: dict[str, Any]) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total and total > max_bytes:
                raise MediaError("Video na odkazu je větší než povolený limit.")
            if total:
                prog.set("upload", d.get("downloaded_bytes", 0) / total, "Stahuji video z odkazu…")

    opts = {
        "outtmpl": out_tmpl,
        "format": "bv*[height<=2160]+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(project.source_url, download=True)
            path = ydl.prepare_filename(info)
    except yt_dlp.utils.DownloadError as e:
        raise MediaError(f"Video z odkazu se nepodařilo stáhnout: {str(e).splitlines()[0][:300]}") from e
    from pathlib import Path

    p = Path(path)
    if not p.exists():  # merged output has .mp4 extension
        cand = sorted(p.parent.glob("source.*"))
        if not cand:
            raise MediaError("Stažený soubor nebyl nalezen.")
        p = cand[0]
    project.source_key = str(p.relative_to(st.local_path("x").parent))
    if info.get("title") and project.name in ("", "Video z odkazu"):
        project.name = str(info["title"])[:200]
    db.commit()


def process_project(project_id: str) -> None:
    """Full pipeline: (download) -> probe -> transcribe -> moments -> reframe -> render."""
    db = get_sessionmaker()()
    try:
        project = db.get(Project, project_id)
        if project is None:
            return
        project.status = "processing"
        project.error = None
        project.started_at = datetime.now(UTC)
        db.commit()
        prog = Progress(db, project)
        try:
            _run_pipeline(db, project, prog)
        except (MediaError, NoSpeechError, LLMError) as e:
            log.warning("project %s failed: %s", project_id, e)
            db.rollback()
            _fail(db, project, str(e))
        except Exception as e:
            log.error("project %s crashed: %s\n%s", project_id, e, traceback.format_exc())
            db.rollback()
            _fail(db, project, "Neočekávaná chyba při zpracování. Podrobnosti jsou v logu workeru.")
    finally:
        db.close()


def _run_pipeline(db: Session, project: Project, prog: Progress) -> None:
    s = get_settings()
    st = get_storage()
    settings = dict(project.settings or {})

    # ---- 1. source -------------------------------------------------------
    if project.source_type == "url" and not project.source_key:
        prog.set("upload", 0.0, "Stahuji video z odkazu…", force=True)
        _download_url(db, project, prog)
    prog.set("upload", 1.0, "Kontroluji video…", force=True)
    src = st.local_path(project.source_key or "")
    info = probe(src)
    if not info.has_audio:
        raise MediaError("Video neobsahuje zvukovou stopu, takže z něj nelze vytvořit přepis.")
    if info.duration > s.max_video_seconds:
        raise MediaError(f"Video je delší než povolený limit {s.max_video_seconds // 3600} h.")
    w, h = info.display_size
    project.duration, project.width, project.height, project.fps = info.duration, w, h, info.fps
    settings["fps_str"] = info.fps_str
    r0 = max(0.0, float(settings.get("range_start") or 0.0))
    r1 = float(settings.get("range_end") or info.duration)
    r1 = min(r1, info.duration) if r1 > 0 else info.duration
    if r1 - r0 < 5:
        raise MediaError("Zvolený časový rozsah je příliš krátký (min. 5 s).")
    settings["range_start"], settings["range_end"] = r0, r1
    project.settings = settings
    thumb_key = f"{project_prefix(project.user_id, project.id)}/thumb.jpg"
    try:
        thumbnail(src, st.local_path(thumb_key), r0 + (r1 - r0) * 0.1, width=480)
        project.thumbnail_key = thumb_key
    except MediaError:
        log.warning("thumbnail failed for %s", project.id)
    db.commit()

    # ---- 2. transcription ---------------------------------------------------
    model_name = settings.get("whisper_model") or s.whisper_model
    prog.set("transcribe", 0.0, "Připravuji zvuk…", force=True)
    wav_key = f"{project_prefix(project.user_id, project.id)}/audio.wav"
    wav = st.local_path(wav_key)
    extract_audio(src, wav, r0, r1)
    if not has_speech_energy(wav):
        raise NoSpeechError("Zvuková stopa je tichá – ve videu není žádná řeč.")
    prog.set("transcribe", 0.02, f"Přepisuji řeč (Whisper {model_name})…", force=True)
    lang = settings.get("language") or "auto"
    tr = transcribe(
        str(wav), model_name=model_name, language=None if lang == "auto" else lang, offset=r0, duration=r1 - r0,
        on_progress=lambda f: prog.set("transcribe", 0.02 + 0.98 * f, f"Přepisuji řeč (Whisper {model_name})…"),
    )
    for i, wd in enumerate(tr["words"]):
        wd["i"] = i
    tkey = f"{project_prefix(project.user_id, project.id)}/transcript.json"
    st.local_path(tkey).write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")
    project.transcript_key = tkey
    project.language = tr["language"]
    st.delete(wav_key)
    db.commit()

    # ---- 3. moments -----------------------------------------------------------
    prog.set("moments", 0.0, "Hledám nejlepší momenty…", force=True)
    provider = get_provider()
    usage: dict[str, Any] = {"provider": provider.name, "model": provider.model}
    try:
        res = finder.find_moments(
            tr["words"], language=tr["language"], length=settings.get("clip_length", "auto"),
            focus=settings.get("focus") or None, provider=provider, bounds=(r0, r1),
            on_progress=lambda f, m: prog.set("moments", f, m),
        )
    except LLMConfigError:
        raise
    usage.update({"input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
                  "cost_usd": res.cost_usd, "windows": res.windows, "failed_windows": res.failed_windows})
    project.llm_usage = usage
    if res.warnings:
        project.message = res.warnings[0]
    for old in list(project.clips):
        db.delete(old)
    db.flush()
    if not res.candidates:
        raise LLMError("AI nenašla ve videu žádné momenty vhodné na klip. Zkuste jiný rozsah, délku nebo téma.")
    clips: list[Clip] = []
    for c in res.candidates:
        new_clip = Clip(
            project_id=project.id, user_id=project.user_id, start=c.start, end=c.end, title=c.title,
            hook=c.hook, reason=c.reason, description=c.description, hashtags=c.hashtags,
            keywords=c.keywords, scores=c.scores, virality_score=c.virality_score,
            render_info={"emojis": c.emojis, "words": len(words_in(tr["words"], c.start, c.end))},
        )
        db.add(new_clip)
        clips.append(new_clip)
    db.commit()

    # ---- 4. reframing (face analysis + preview excerpts) ---------------------
    for n, clip in enumerate(clips):
        prog.set("reframe", n / len(clips), f"Analyzuji obličeje a záběry ({n + 1}/{len(clips)})…")
        try:
            ensure_preview_and_analysis(db, project, clip, clip.start, clip.end)
        except MediaError as e:
            clip.render_status, clip.render_error = "failed", str(e)
            db.commit()
    prog.set("reframe", 1.0, force=True)

    # ---- 5. render ------------------------------------------------------------
    if s.render_on_process:
        for n, clip in enumerate(clips):
            if clip.render_status == "failed":
                continue
            base = n / len(clips)
            prog.set("render", base, f"Renderuji klip {n + 1}/{len(clips)}…")
            clip.render_status = "rendering"
            db.commit()
            try:
                def on_render(f: float, b: float = base) -> None:
                    prog.set("render", b + f / len(clips))

                render_clip(db, clip, on_progress=on_render)
            except MediaError as e:
                db.rollback()
                clip.render_status, clip.render_error = "failed", str(e)
                db.commit()
    project.status = "done"
    project.step = "done"
    project.progress = 100.0
    project.eta_seconds = None
    project.finished_at = datetime.now(UTC)
    if not res.warnings:
        project.message = f"Hotovo – {len(clips)} klipů."
    db.commit()


def rerender_clip(clip_id: str) -> None:
    db = get_sessionmaker()()
    try:
        clip = db.get(Clip, clip_id)
        if clip is None:
            return
        clip.render_status = "rendering"
        clip.render_progress = 0.0
        db.commit()
        last = [0.0]

        def on_progress(f: float) -> None:
            if time.monotonic() - last[0] > 1.0:
                clip.render_progress = round(f * 100, 1)
                db.commit()
                last[0] = time.monotonic()

        try:
            render_clip(db, clip, on_progress=on_progress)
        except Exception as e:
            log.error("render %s failed: %s\n%s", clip_id, e, traceback.format_exc())
            db.rollback()
            clip.render_status = "failed"
            clip.render_error = str(e) if isinstance(e, MediaError) else "Render selhal. Podrobnosti v logu workeru."
            db.commit()
    finally:
        db.close()


def safe_filename(name: str, fallback: str = "klip") -> str:
    import re
    import unicodedata

    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    n = re.sub(r"[^A-Za-z0-9]+", "-", n).strip("-").lower()
    return (n or fallback)[:60]


def export_zip(export_id: str) -> None:
    """Render dirty clips and pack MP4 + SRT + TXT for every clip into a ZIP."""
    db = get_sessionmaker()()
    st = get_storage()
    try:
        ex = db.get(ExportJob, export_id)
        if ex is None:
            return
        ex.status = "running"
        db.commit()
        try:
            project = db.get(Project, ex.project_id)
            assert project is not None
            clips = db.scalars(
                select(Clip).where(Clip.project_id == project.id).order_by(Clip.virality_score.desc())
            ).all()
            if not clips:
                raise MediaError("Projekt nemá žádné klipy.")
            from app.services.clip_render import effective_edit, load_transcript

            transcript = load_transcript(project)
            for n, clip in enumerate(clips):
                if clip.dirty or clip.render_status != "ready" or not clip.video_key or not st.exists(clip.video_key):
                    ex.message = f"Renderuji klip {n + 1}/{len(clips)}…"
                    db.commit()
                    render_clip(db, clip)
                ex.progress = round((n + 1) / len(clips) * 80, 1)
                db.commit()
            key = f"{project_prefix(project.user_id, project.id)}/exports/{ex.id}.zip"
            zpath = st.local_path(key)
            ex.message = "Balím ZIP…"
            db.commit()
            with zipfile.ZipFile(zpath, "w") as zf:
                for n, clip in enumerate(clips, 1):
                    base = f"{n:02d}-{safe_filename(clip.title)}"
                    assert clip.video_key and clip.srt_key
                    zf.write(st.local_path(clip.video_key), f"{base}.mp4", compress_type=zipfile.ZIP_STORED)
                    zf.write(st.local_path(clip.srt_key), f"{base}.srt", compress_type=zipfile.ZIP_DEFLATED)
                    edit = effective_edit(project, clip)
                    zf.writestr(f"{base}.txt", clip_text(clip, transcript["words"], edit), compress_type=zipfile.ZIP_DEFLATED)
                zf.writestr("prepis-cely.txt", full_transcript_text(transcript), compress_type=zipfile.ZIP_DEFLATED)
            ex.zip_key = key
            ex.status = "ready"
            ex.progress = 100.0
            ex.message = "ZIP je připraven."
            db.commit()
        except Exception as e:
            log.error("export %s failed: %s\n%s", export_id, e, traceback.format_exc())
            db.rollback()
            ex.status = "failed"
            ex.message = str(e) if isinstance(e, MediaError) else "Export selhal."
            db.commit()
    finally:
        db.close()


def clip_text(clip: Clip, words: list[dict[str, Any]], edit: dict[str, Any]) -> str:
    edits = edit.get("word_edits") or {}
    ws = [str(edits.get(str(w.get("i")), w["w"])) for w in words_in(words, clip.start, clip.end)]
    body = " ".join(x for x in ws if x)
    tags = " ".join(clip.hashtags or [])
    return (
        f"{clip.title}\n\nVirality Score: {clip.virality_score:.0f}/100\n"
        f"Popisek: {clip.description}\n{tags}\n\nPřepis:\n{body}\n"
    )


def full_transcript_text(transcript: dict[str, Any]) -> str:
    lines = []
    for seg in transcript.get("segments", []):
        t = int(seg["s"])
        lines.append(f"[{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}] {seg['text']}")
    return "\n".join(lines) + "\n"
