"""Render one clip from DB state (shared by the pipeline, re-render and export jobs)."""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BrandTemplate, Clip, Font, Preset, Project
from app.pipeline import captions, reframe, render
from app.pipeline.emoji import render_emoji_png
from app.pipeline.media import preview_excerpt, thumbnail
from app.pipeline.presets import resolve_style
from app.pipeline.timeline import build_timemap, map_words
from app.storage import get_storage, project_prefix

log = logging.getLogger(__name__)

PREVIEW_MARGIN = 30.0  # seconds of context around a clip in the editor preview / face analysis

DEFAULT_EDIT: dict[str, Any] = {
    "aspect": "9:16",
    "resolution": "1080",
    "layout": "auto",
    "preset_id": "bold-pop",
    "style": {},
    "word_edits": {},
    "remove_silence": False,
    "remove_fillers": False,
    "hook_enabled": False,
    "hook_text": "",
    "brand_template_id": None,
    "captions_enabled": True,
}


def effective_edit(project: Project, clip: Clip) -> dict[str, Any]:
    ps = project.settings or {}
    base = dict(DEFAULT_EDIT)
    for k in ("aspect", "resolution", "layout", "preset_id", "brand_template_id"):
        if ps.get(k) is not None:
            base[k] = ps[k]
    if ps.get("style"):
        base["style"] = dict(ps["style"])
    base["hook_text"] = clip.hook or clip.title
    base.update({k: v for k, v in (clip.edit or {}).items() if v is not None})
    return base


def load_transcript(project: Project) -> dict[str, Any]:
    if not project.transcript_key:
        raise RuntimeError("Projekt nemá přepis.")
    with open(get_storage().local_path(project.transcript_key), encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def user_presets(db: Session, user_id: str) -> dict[str, dict[str, Any]]:
    rows = db.scalars(select(Preset).where(Preset.user_id == user_id)).all()
    return {f"user:{p.id}": p.style for p in rows}


def user_fonts(db: Session, user_id: str) -> dict[str, dict[str, Any]]:
    rows = db.scalars(select(Font).where(Font.user_id == user_id)).all()
    st = get_storage()
    return {
        f"user:{f.id}": {
            "id": f"user:{f.id}", "family": f.family, "file": str(st.local_path(f.storage_key)), "weight": 400,
        }
        for f in rows
    }


def ensure_preview_and_analysis(db: Session, project: Project, clip: Clip, start: float, end: float) -> dict[str, Any]:
    """Make sure the editor preview excerpt and the face analysis cover [start, end]."""
    st = get_storage()
    src = st.local_path(project.source_key or "")
    duration = project.duration or end
    lo = max(0.0, start - PREVIEW_MARGIN)
    hi = min(duration, end + PREVIEW_MARGIN)
    prefix = f"{project_prefix(project.user_id, project.id)}/clips/{clip.id}"
    analysis: dict[str, Any] | None = None
    if clip.analysis_key and st.exists(clip.analysis_key):
        with open(st.local_path(clip.analysis_key), encoding="utf-8") as f:
            analysis = json.load(f)
        assert analysis is not None
        if analysis["start"] > start + 0.5 or analysis["end"] < end - 0.5:
            analysis = None
    if analysis is None:
        analysis = reframe.analyze(src, lo, hi, project.width or 1920, project.height or 1080)
        key = f"{prefix}/analysis.json"
        st.local_path(key).write_text(json.dumps(analysis), encoding="utf-8")
        clip.analysis_key = key
    need_preview = not (clip.preview_key and st.exists(clip.preview_key))
    if not need_preview:
        p_end = clip.preview_offset + float(clip.render_info.get("preview_duration", 0) or 0)
        need_preview = clip.preview_offset > start + 0.2 or bool(p_end and p_end < end - 0.2)
    if need_preview:
        key = f"{prefix}/preview.mp4"
        preview_excerpt(src, st.local_path(key), lo, hi)
        clip.preview_key = key
        clip.preview_offset = lo
        clip.render_info = {**(clip.render_info or {}), "preview_duration": round(hi - lo, 3)}
    db.commit()
    return analysis


def render_clip(db: Session, clip: Clip, on_progress: Callable[[float], None] | None = None,
                preset: str | None = None) -> None:
    s = get_settings()
    st = get_storage()
    project = clip.project
    edit = effective_edit(project, clip)
    transcript = load_transcript(project)
    words = transcript["words"]
    lang = transcript.get("language", "cs")
    start, end = float(clip.start), float(clip.end)

    analysis = ensure_preview_and_analysis(db, project, clip, start, end)
    tm, kept = build_timemap(
        words, start, end,
        remove_silence=bool(edit["remove_silence"]), remove_fillers=bool(edit["remove_fillers"]), lang=lang,
    )
    out_words = map_words(captions.apply_word_edits(kept, edit.get("word_edits")), tm)

    probe_w, probe_h = int(project.width or 1920), int(project.height or 1080)
    target_w, target_h = render.ASPECTS.get(edit["aspect"], render.ASPECTS["9:16"])
    plan = reframe.plan_crop(analysis, target_w, target_h, edit.get("layout", "auto"))
    W, H, upscale = render.output_size(edit["aspect"], edit.get("resolution", "1080"), plan.crop_w, plan.crop_h,
                                       split=plan.layout == "split")
    if plan.layout == "blur":  # the whole frame is fitted inside the output
        upscale = round(min(W / max(1, probe_w), H / max(1, probe_h)), 3)

    ufonts = user_fonts(db, project.user_id)
    style = resolve_style(edit["preset_id"], edit.get("style"), user_presets(db, project.user_id))
    brand: BrandTemplate | None = None
    if edit.get("brand_template_id"):
        brand = db.get(BrandTemplate, edit["brand_template_id"])
        if brand and brand.user_id != project.user_id:
            brand = None
    if brand:
        style["highlight_color"] = brand.accent_color or style["highlight_color"]
        style["text_color"] = brand.primary_color or style["text_color"]
        if brand.font_id:
            style["font"] = brand.font_id

    prefix = f"{project_prefix(project.user_id, project.id)}/clips/{clip.id}"
    work = st.local_path(f"{prefix}/work/x").parent
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    # fonts dir for libass: built-in fonts + the user's uploaded fonts
    font_files = sorted(s.fonts_dir.glob("*.ttf")) + sorted(s.fonts_dir.glob("*.otf"))
    font_files += [Path(f["file"]) for f in ufonts.values()]
    fonts_dir = render.link_fonts(work / "fonts", font_files)

    ass_path = None
    overlays: list[render.Overlay] = []
    if edit.get("captions_enabled", True) or (edit.get("hook_enabled") and edit.get("hook_text")):
        ass_doc = captions.build_ass(
            out_words if edit.get("captions_enabled", True) else [], style, W, H,
            keywords=clip.keywords or [],
            hook_text=edit.get("hook_text") if edit.get("hook_enabled") else None,
            user_fonts=ufonts, duration=tm.duration,
        )
        ass_path = work / "captions.ass"
        ass_path.write_text(ass_doc, encoding="utf-8")
        if edit.get("captions_enabled", True):
            size, cx, cy = captions.emoji_geometry(style, W, H)
            emojis = clip.render_info.get("emojis") or []
            for n, ev in enumerate(captions.emoji_events(out_words, style, W, H, emojis, lang)):
                png = work / f"emoji{n}.png"
                if render_emoji_png(ev["emoji"], png, size):
                    overlays.append(render.Overlay(png, ev["start"], ev["end"], cx, cy))

    logo = None
    if brand and brand.logo_key and st.exists(brand.logo_key):
        logo = render.LogoSpec(st.local_path(brand.logo_key), brand.logo_position, brand.logo_opacity, brand.logo_scale)

    video_key = f"{prefix}/clip.mp4"
    tmp_out = work / "render.mp4"
    spec = render.RenderSpec(
        src=st.local_path(project.source_key or ""), src_w=probe_w, src_h=probe_h,
        fps_str=str(project.settings.get("fps_str") or f"{project.fps or 30:.3f}"),
        has_audio=True, start=start, end=end, timemap=tm, out_w=W, out_h=H, plan=plan,
        out_path=tmp_out, work_dir=work, ass_path=ass_path, fonts_dir=fonts_dir, overlays=overlays, logo=logo,
        preset=preset,
    )
    render.render(spec, float(project.fps or 30.0), on_progress)

    final = tmp_out
    if brand and (brand.intro_key or brand.outro_key):
        final = work / "branded.mp4"
        render.concat_intro_outro(
            tmp_out,
            st.local_path(brand.intro_key) if brand.intro_key and st.exists(brand.intro_key) else None,
            st.local_path(brand.outro_key) if brand.outro_key and st.exists(brand.outro_key) else None,
            final, W, H, spec.fps_str, True,
        )
    shutil.move(str(final), st.local_path(video_key))
    st.commit(video_key)

    thumb_key = f"{prefix}/thumb.jpg"
    thumbnail(st.local_path(video_key), st.local_path(thumb_key), min(1.0, tm.duration / 3), width=360)
    srt_key = f"{prefix}/captions.srt"
    st.local_path(srt_key).write_text(captions.build_srt(out_words), encoding="utf-8")

    clip.video_key, clip.thumb_key, clip.srt_key = video_key, thumb_key, srt_key
    info = dict(clip.render_info or {})
    info.update({
        "width": W, "height": H, "layout": plan.layout, "upscale": upscale,
        "duration": round(tm.duration, 3), "face_ratio": round(plan.face_ratio, 3), "speakers": plan.speakers,
        "segments": len(tm.segments), "detector": analysis.get("detector"),
    })
    clip.render_info = info
    clip.render_status = "ready"
    clip.render_progress = 100.0
    clip.render_error = None
    clip.dirty = False
    shutil.rmtree(work, ignore_errors=True)
    db.commit()
