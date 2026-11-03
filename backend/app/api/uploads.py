"""Resumable chunked uploads: init -> PUT chunks at offsets -> (auto) complete."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser
from app.config import get_settings
from app.models import Upload
from app.storage import get_storage, user_prefix

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".ts", ".flv", ".wmv", ".3gp"}


class InitBody(BaseModel):
    filename: str = Field(min_length=1, max_length=400)
    size: int = Field(gt=0)


def _out(u: Upload) -> dict[str, object]:
    return {
        "id": u.id, "filename": u.filename, "size": u.size, "received": u.received, "status": u.status,
        "chunk_size": get_settings().upload_chunk_bytes,
    }


def _owned(db: DB, user: CurrentUser, upload_id: str) -> Upload:
    u = db.get(Upload, upload_id)
    if u is None or u.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload nenalezen.")
    return u


@router.post("", status_code=201)
def init_upload(body: InitBody, db: DB, user: CurrentUser) -> dict[str, object]:
    s = get_settings()
    if body.size > s.max_upload_bytes:
        gb = s.max_upload_bytes / 1024**3
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Soubor je příliš velký (limit {gb:.1f} GB).")
    ext = "." + body.filename.rsplit(".", 1)[-1].lower() if "." in body.filename else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Nepodporovaný typ souboru. Nahrajte video (MP4, MOV, MKV, WEBM…).")
    u = Upload(user_id=user.id, filename=body.filename, size=body.size, storage_key="")
    db.add(u)
    db.flush()
    u.storage_key = f"{user_prefix(user.id)}/uploads/{u.id}{ext}"
    db.commit()
    return _out(u)


@router.get("/{upload_id}")
def upload_status(upload_id: str, db: DB, user: CurrentUser) -> dict[str, object]:
    return _out(_owned(db, user, upload_id))


@router.put("/{upload_id}")
async def put_chunk(upload_id: str, offset: int, request: Request, db: DB, user: CurrentUser) -> dict[str, object]:
    u = _owned(db, user, upload_id)
    if u.status != "uploading":
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload už je dokončen.")
    if offset != u.received:
        # client and server disagree (e.g. after a dropped connection) -> client resumes from `received`
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"message": "Nesouhlasí pozice", "received": u.received})
    st = get_storage()
    path = st.local_path(u.storage_key)
    mode = "r+b" if path.exists() else "wb"
    written = 0
    limit = get_settings().upload_chunk_bytes * 2
    with open(path, mode) as f:
        f.seek(offset)
        async for data in request.stream():
            written += len(data)
            if written > limit or offset + written > u.size:
                f.truncate(offset)
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Část souboru je příliš velká.")
            f.write(data)
        f.truncate(offset + written)
    u.received = offset + written
    if u.received >= u.size:
        u.status = "complete"
    db.commit()
    return _out(u)


@router.delete("/{upload_id}")
def cancel_upload(upload_id: str, db: DB, user: CurrentUser) -> dict[str, bool]:
    u = _owned(db, user, upload_id)
    get_storage().delete(u.storage_key)
    db.delete(u)
    db.commit()
    return {"ok": True}
