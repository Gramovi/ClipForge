from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, owned_project
from app.config import get_settings
from app.db import get_sessionmaker
from app.models import Clip, ExportJob, Project, Upload
from app.pipeline.moments import LENGTH_RANGES
from app.pipeline.presets import builtin_ids
from app.pipeline.transcribe import LANGUAGES, WHISPER_MODELS
from app.queue import QUEUE_PROCESS, QUEUE_RENDER, cancel_job, enqueue
from app.storage import get_storage, project_prefix

router = APIRouter(prefix="/api", tags=["projects"])


class ProjectSettings(BaseModel):
    clip_length: Literal["auto", "lt30", "30-60", "60-90", "90-180"] = "auto"
    aspect: Literal["9:16", "1:1", "16:9"] = "9:16"
    resolution: Literal["1080", "2160", "source"] = "1080"
    layout: Literal["auto", "track", "split", "blur", "center"] = "auto"
    language: str = "auto"
    preset_id: str = "bold-pop"
    style: dict[str, Any] = Field(default_factory=dict)
    focus: str | None = Field(default=None, max_length=300)
    range_start: float | None = Field(default=None, ge=0)
    range_end: float | None = Field(default=None, ge=0)
    whisper_model: str | None = None
    brand_template_id: str | None = None

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        if v not in LANGUAGES:
            raise ValueError("nepodporovaný jazyk")
        return v

    @field_validator("whisper_model")
    @classmethod
    def _model(cls, v: str | None) -> str | None:
        if v and v not in {m["id"] for m in WHISPER_MODELS}:
            raise ValueError("neznámý model")
        return v or None


class CreateProject(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    upload_id: str | None = None
    url: str | None = Field(default=None, max_length=2000)
    settings: ProjectSettings = Field(default_factory=ProjectSettings)


class PatchProject(BaseModel):
    name: str = Field(min_length=1, max_length=300)


def clip_out(c: Clip) -> dict[str, Any]:
    return {
        "id": c.id, "project_id": c.project_id, "start": c.start, "end": c.end, "duration": round(c.end - c.start, 2),
        "title": c.title, "hook": c.hook, "reason": c.reason, "description": c.description,
        "hashtags": c.hashtags or [], "keywords": c.keywords or [], "scores": c.scores or {},
        "virality_score": c.virality_score, "render_status": c.render_status,
        "render_progress": c.render_progress, "render_error": c.render_error, "dirty": c.dirty,
        "render_info": {k: v for k, v in (c.render_info or {}).items() if k != "emojis"},
        "has_video": bool(c.video_key), "edit": c.edit or {},
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def project_out(p: Project, clip_count: int | None = None) -> dict[str, Any]:
    return {
        "id": p.id, "name": p.name, "status": p.status, "step": p.step, "progress": p.progress,
        "step_progress": p.step_progress, "eta_seconds": p.eta_seconds, "message": p.message, "error": p.error,
        "source_type": p.source_type, "source_url": p.source_url, "duration": p.duration, "width": p.width,
        "height": p.height, "fps": p.fps, "language": p.language, "settings": p.settings or {},
        "llm_usage": p.llm_usage or {}, "has_thumbnail": bool(p.thumbnail_key),
        "clip_count": clip_count if clip_count is not None else len(p.clips),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/projects")
def list_projects(db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    q = select(Clip.project_id, func.count(Clip.id)).where(Clip.user_id == user.id).group_by(Clip.project_id)
    counts: dict[str, int] = {str(pid): int(n) for pid, n in db.execute(q).all()}
    rows = db.scalars(select(Project).where(Project.user_id == user.id).order_by(Project.created_at.desc())).all()
    return [project_out(p, counts.get(p.id, 0)) for p in rows]


@router.post("/projects", status_code=201)
def create_project(body: CreateProject, db: DB, user: CurrentUser) -> dict[str, Any]:
    s = get_settings()
    if bool(body.upload_id) == bool(body.url):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Zadejte buď nahraný soubor, nebo odkaz.")
    if body.settings.preset_id not in builtin_ids() and not body.settings.preset_id.startswith("user:"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Neznámý preset titulků.")
    rs, re_ = body.settings.range_start, body.settings.range_end
    if rs is not None and re_ is not None and re_ and re_ - rs < 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Časový rozsah musí mít alespoň 5 sekund.")
    settings = body.settings.model_dump()
    p = Project(user_id=user.id, name=(body.name or "").strip() or "Nový projekt", settings=settings, status="queued",
                step="upload", progress=0.0)
    if body.url:
        if not s.allow_url_import:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Import z odkazu je vypnutý.")
        if not body.url.startswith(("http://", "https://")):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Neplatný odkaz.")
        p.source_type, p.source_url = "url", body.url
        if not body.name:
            p.name = "Video z odkazu"
        db.add(p)
        db.flush()
    else:
        up = db.get(Upload, body.upload_id)
        if up is None or up.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nahraný soubor nenalezen.")
        if up.status != "complete":
            raise HTTPException(status.HTTP_409_CONFLICT, "Soubor ještě není celý nahraný.")
        if not body.name:
            p.name = up.filename.rsplit(".", 1)[0][:200]
        db.add(p)
        db.flush()
        st = get_storage()
        ext = up.storage_key.rsplit(".", 1)[-1]
        key = f"{project_prefix(user.id, p.id)}/source.{ext}"
        shutil.move(str(st.local_path(up.storage_key)), st.local_path(key))
        p.source_key = key
        up.status = "used"
    db.commit()
    p.job_id = enqueue(QUEUE_PROCESS, "app.jobs.process_project", p.id)
    db.commit()
    return project_out(p, 0)


@router.get("/projects/{project_id}")
def get_project(project_id: str, db: DB, user: CurrentUser) -> dict[str, Any]:
    p = owned_project(db, user, project_id)
    out = project_out(p)
    out["clips"] = [clip_out(c) for c in sorted(p.clips, key=lambda c: -c.virality_score)]
    return out


@router.patch("/projects/{project_id}")
def rename_project(project_id: str, body: PatchProject, db: DB, user: CurrentUser) -> dict[str, Any]:
    p = owned_project(db, user, project_id)
    p.name = body.name.strip()
    db.commit()
    return project_out(p)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, db: DB, user: CurrentUser) -> dict[str, bool]:
    p = owned_project(db, user, project_id)
    cancel_job(p.job_id)
    get_storage().delete_prefix(project_prefix(user.id, p.id))
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/retry")
def retry_project(project_id: str, db: DB, user: CurrentUser) -> dict[str, Any]:
    p = owned_project(db, user, project_id)
    if p.status not in ("failed", "done"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Projekt se právě zpracovává.")
    if not p.source_key and p.source_type != "url":
        raise HTTPException(status.HTTP_409_CONFLICT, "Zdrojové video chybí, nahrajte ho znovu.")
    p.status, p.error, p.progress, p.step, p.message = "queued", None, 0.0, "upload", None
    db.commit()
    p.job_id = enqueue(QUEUE_PROCESS, "app.jobs.process_project", p.id)
    db.commit()
    return project_out(p)


def _snapshot(project_id: str, user_id: str) -> dict[str, Any] | None:
    db = get_sessionmaker()()
    try:
        p = db.get(Project, project_id)
        if p is None or p.user_id != user_id:
            return None
        out = project_out(p)
        out["clips_ready"] = sum(1 for c in p.clips if c.render_status == "ready")
        return out
    finally:
        db.close()


@router.get("/projects/{project_id}/events")
async def project_events(project_id: str, request: Request, db: DB, user: CurrentUser) -> StreamingResponse:
    """Server-Sent Events with live progress. The pipeline runs in the worker; this only reads state."""
    owned_project(db, user, project_id)
    uid = user.id

    async def gen() -> AsyncIterator[str]:
        last = None
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            snap = await asyncio.to_thread(_snapshot, project_id, uid)
            if snap is None:
                yield "event: gone\ndata: {}\n\n"
                return
            payload = json.dumps(snap, ensure_ascii=False)
            if payload != last:
                yield f"event: progress\ndata: {payload}\n\n"
                last = payload
                idle = 0
            else:
                idle += 1
                if idle % 15 == 0:
                    yield ": keep-alive\n\n"
            if snap["status"] in ("done", "failed"):
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(1.0)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


@router.get("/projects/{project_id}/thumbnail")
def project_thumbnail(project_id: str, db: DB, user: CurrentUser) -> FileResponse:
    p = owned_project(db, user, project_id)
    st = get_storage()
    if not p.thumbnail_key or not st.exists(p.thumbnail_key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Náhled není k dispozici.")
    return FileResponse(st.local_path(p.thumbnail_key), media_type="image/jpeg")


@router.get("/projects/{project_id}/transcript.txt")
def project_transcript(project_id: str, db: DB, user: CurrentUser) -> PlainTextResponse:
    from app.jobs import full_transcript_text, safe_filename
    from app.services.clip_render import load_transcript

    p = owned_project(db, user, project_id)
    if not p.transcript_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Přepis zatím neexistuje.")
    txt = full_transcript_text(load_transcript(p))
    fn = safe_filename(p.name, "prepis") + ".txt"
    return PlainTextResponse(txt, media_type="text/plain; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{fn}"'})


# ---- export ZIP -------------------------------------------------------------------

def export_out(e: ExportJob) -> dict[str, Any]:
    return {"id": e.id, "project_id": e.project_id, "status": e.status, "progress": e.progress, "message": e.message}


@router.post("/projects/{project_id}/export", status_code=201)
def start_export(project_id: str, db: DB, user: CurrentUser) -> dict[str, Any]:
    p = owned_project(db, user, project_id)
    if p.status != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "Projekt ještě není zpracovaný.")
    ex = ExportJob(user_id=user.id, project_id=p.id)
    db.add(ex)
    db.commit()
    enqueue(QUEUE_RENDER, "app.jobs.export_zip", ex.id)
    return export_out(ex)


def _owned_export(db: DB, user: CurrentUser, export_id: str) -> ExportJob:
    e = db.get(ExportJob, export_id)
    if e is None or e.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export nenalezen.")
    return e


@router.get("/exports/{export_id}")
def get_export(export_id: str, db: DB, user: CurrentUser) -> dict[str, Any]:
    return export_out(_owned_export(db, user, export_id))


@router.get("/exports/{export_id}/download")
def download_export(export_id: str, db: DB, user: CurrentUser) -> FileResponse:
    from app.jobs import safe_filename

    e = _owned_export(db, user, export_id)
    st = get_storage()
    if e.status != "ready" or not e.zip_key or not st.exists(e.zip_key):
        raise HTTPException(status.HTTP_409_CONFLICT, "ZIP ještě není připraven.")
    p = db.get(Project, e.project_id)
    name = safe_filename(p.name if p else "klipy", "klipy") + "-klipy.zip"
    return FileResponse(st.local_path(e.zip_key), media_type="application/zip", filename=name)


@router.get("/options")
def options() -> dict[str, Any]:
    """Static option lists for the UI."""
    return {
        "languages": LANGUAGES,
        "whisper_models": WHISPER_MODELS,
        "lengths": {k: {"min": v[0], "max": v[1]} for k, v in LENGTH_RANGES.items()},
    }
