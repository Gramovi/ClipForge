from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser, owned_clip
from app.api.projects import clip_out
from app.jobs import clip_text, safe_filename
from app.models import BrandTemplate
from app.pipeline.moments import words_in
from app.pipeline.presets import builtin_ids
from app.queue import QUEUE_RENDER, enqueue
from app.services.clip_render import effective_edit, load_transcript
from app.storage import get_storage

router = APIRouter(prefix="/api/clips", tags=["clips"])


class EditBody(BaseModel):
    aspect: Literal["9:16", "1:1", "16:9"] | None = None
    resolution: Literal["1080", "2160", "source"] | None = None
    layout: Literal["auto", "track", "split", "blur", "center"] | None = None
    preset_id: str | None = None
    style: dict[str, Any] | None = None
    word_edits: dict[str, str] | None = None
    remove_silence: bool | None = None
    remove_fillers: bool | None = None
    hook_enabled: bool | None = None
    hook_text: str | None = Field(default=None, max_length=200)
    brand_template_id: str | None = None
    captions_enabled: bool | None = None


class PatchClip(BaseModel):
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    hashtags: list[str] | None = None
    edit: EditBody | None = None


@router.get("/{clip_id}")
def get_clip(clip_id: str, db: DB, user: CurrentUser) -> dict[str, Any]:
    clip = owned_clip(db, user, clip_id)
    project = clip.project
    out = clip_out(clip)
    out["effective_edit"] = effective_edit(project, clip)
    out["emojis"] = (clip.render_info or {}).get("emojis", [])
    out["language"] = project.language
    out["preview_offset"] = clip.preview_offset
    out["preview_duration"] = (clip.render_info or {}).get("preview_duration")
    out["has_preview"] = bool(clip.preview_key)
    out["project"] = {"id": project.id, "name": project.name, "duration": project.duration,
                      "width": project.width, "height": project.height, "fps": project.fps}
    words: list[dict[str, Any]] = []
    if project.transcript_key:
        tr = load_transcript(project)
        lo = clip.preview_offset if clip.preview_key else max(0.0, clip.start - 30)
        hi = lo + float((clip.render_info or {}).get("preview_duration") or (clip.end - clip.start + 60))
        words = words_in(tr["words"], lo, hi)
    out["words"] = words
    return out


@router.patch("/{clip_id}")
def patch_clip(clip_id: str, body: PatchClip, db: DB, user: CurrentUser) -> dict[str, Any]:
    clip = owned_clip(db, user, clip_id)
    project = clip.project
    start = body.start if body.start is not None else clip.start
    end = body.end if body.end is not None else clip.end
    if end - start < 1.0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Klip musí být dlouhý alespoň 1 sekundu.")
    if end - start > 600:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Klip může mít nejvýše 10 minut.")
    if project.duration and end > project.duration + 0.01:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Konec klipu je za koncem videa.")
    changed = start != clip.start or end != clip.end
    clip.start, clip.end = round(start, 3), round(end, 3)
    if body.title is not None:
        clip.title = body.title.strip()
    if body.description is not None:
        clip.description = body.description
    if body.hashtags is not None:
        clip.hashtags = [h if h.startswith("#") else f"#{h}" for h in (t.strip().replace(" ", "") for t in body.hashtags) if h][:10]
    if body.edit is not None:
        upd = body.edit.model_dump(exclude_none=True)
        if "preset_id" in upd and upd["preset_id"] not in builtin_ids() and not upd["preset_id"].startswith("user:"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Neznámý preset.")
        if upd.get("brand_template_id"):
            bt = db.get(BrandTemplate, upd["brand_template_id"])
            if bt is None or bt.user_id != user.id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Brand template nenalezena.")
        if "brand_template_id" in body.edit.model_fields_set and body.edit.brand_template_id is None:
            upd["brand_template_id"] = ""
        edit = dict(clip.edit or {})
        edit.update(upd)
        clip.edit = edit
        changed = True
    if changed:
        clip.dirty = True
    db.commit()
    return clip_out(clip)


@router.post("/{clip_id}/render")
def render_clip(clip_id: str, db: DB, user: CurrentUser) -> dict[str, Any]:
    clip = owned_clip(db, user, clip_id)
    if clip.render_status in ("queued", "rendering"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Klip se už renderuje.")
    clip.render_status = "queued"
    clip.render_progress = 0.0
    db.commit()
    enqueue(QUEUE_RENDER, "app.jobs.rerender_clip", clip.id)
    return clip_out(clip)


@router.delete("/{clip_id}")
def delete_clip(clip_id: str, db: DB, user: CurrentUser) -> dict[str, bool]:
    clip = owned_clip(db, user, clip_id)
    get_storage().delete_prefix(f"users/{user.id}/projects/{clip.project_id}/clips/{clip.id}")
    db.delete(clip)
    db.commit()
    return {"ok": True}


def _file(key: str | None, media: str, filename: str | None = None) -> FileResponse:
    st = get_storage()
    if not key or not st.exists(key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Soubor zatím neexistuje.")
    return FileResponse(st.local_path(key), media_type=media, filename=filename)


@router.get("/{clip_id}/video")
def clip_video(clip_id: str, db: DB, user: CurrentUser, download: bool = False) -> FileResponse:
    clip = owned_clip(db, user, clip_id)
    return _file(clip.video_key, "video/mp4", f"{safe_filename(clip.title)}.mp4" if download else None)


@router.get("/{clip_id}/preview")
def clip_preview(clip_id: str, db: DB, user: CurrentUser) -> FileResponse:
    clip = owned_clip(db, user, clip_id)
    return _file(clip.preview_key, "video/mp4")


@router.get("/{clip_id}/thumb")
def clip_thumb(clip_id: str, db: DB, user: CurrentUser) -> FileResponse:
    clip = owned_clip(db, user, clip_id)
    return _file(clip.thumb_key, "image/jpeg")


@router.get("/{clip_id}/srt")
def clip_srt(clip_id: str, db: DB, user: CurrentUser) -> FileResponse:
    clip = owned_clip(db, user, clip_id)
    return _file(clip.srt_key, "application/x-subrip; charset=utf-8", f"{safe_filename(clip.title)}.srt")


@router.get("/{clip_id}/txt")
def clip_txt(clip_id: str, db: DB, user: CurrentUser) -> PlainTextResponse:
    clip = owned_clip(db, user, clip_id)
    tr = load_transcript(clip.project)
    txt = clip_text(clip, tr["words"], effective_edit(clip.project, clip))
    fn = f"{safe_filename(clip.title)}.txt"
    return PlainTextResponse(txt, media_type="text/plain; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@router.get("/{clip_id}/plan")
def clip_plan(clip_id: str, db: DB, user: CurrentUser, aspect: str = "9:16", layout: str = "auto") -> dict[str, Any]:
    """Crop path for the editor preview, computed by the same code as the final render."""
    import json as _json

    from app.pipeline import reframe, render

    clip = owned_clip(db, user, clip_id)
    st = get_storage()
    if not clip.analysis_key or not st.exists(clip.analysis_key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analýza záběru zatím neexistuje.")
    with open(st.local_path(clip.analysis_key), encoding="utf-8") as f:
        analysis = _json.load(f)
    if aspect not in render.ASPECTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Neplatný poměr stran.")
    if layout not in ("auto", "track", "split", "blur", "center"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Neplatný layout.")
    out_w, out_h = render.ASPECTS[aspect]
    plan = reframe.plan_crop(analysis, out_w, out_h, layout)
    return {
        "layout": plan.layout, "crop_w": plan.crop_w, "crop_h": plan.crop_h,
        "src_w": analysis["src_w"], "src_h": analysis["src_h"], "out_w": out_w, "out_h": out_h,
        "times": [round(t, 3) for t in plan.times], "xs": [round(x, 1) for x in plan.xs],
        "ys": [round(y, 1) for y in plan.ys],
        "xs2": [round(x, 1) for x in plan.xs2] if plan.xs2 else None,
        "ys2": [round(y, 1) for y in plan.ys2] if plan.ys2 else None,
        "face_ratio": plan.face_ratio, "speakers": plan.speakers,
    }
