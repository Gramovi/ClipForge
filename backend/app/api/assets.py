"""Caption presets, fonts, brand templates and system info."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.config import get_settings
from app.llm import LLMConfigError, get_provider
from app.llm.pricing import PRICES, estimate_hour
from app.models import BrandTemplate, Font, Preset
from app.pipeline.presets import builtin_ids, load_presets_file, sanitize_style
from app.storage import get_storage, user_prefix

router = APIRouter(prefix="/api", tags=["assets"])

MAX_FONT_BYTES = 15 * 1024**2
MAX_LOGO_BYTES = 10 * 1024**2
MAX_BUMPER_BYTES = 300 * 1024**2


# ---- presets ------------------------------------------------------------------

@router.get("/presets")
def get_presets(db: DB, user: CurrentUser) -> dict[str, Any]:
    data = load_presets_file()
    fonts = [{**f, "url": f"/api/fonts/builtin/{f['file']}"} for f in data["fonts"]]
    for f in db.scalars(select(Font).where(Font.user_id == user.id)).all():
        fonts.append({"id": f"user:{f.id}", "label": f"{f.family} (vlastní)", "family": f.family,
                      "file": f.filename, "weight": 400, "url": f"/api/fonts/user/{f.id}", "custom": True})
    user_presets = [
        {"id": f"user:{p.id}", "name": p.name, "description": "Vlastní preset", "base_id": p.base_id, "style": p.style,
         "custom": True}
        for p in db.scalars(select(Preset).where(Preset.user_id == user.id).order_by(Preset.created_at)).all()
    ]
    from app.pipeline.emoji import FALLBACK

    return {"defaults": data["defaults"], "presets": data["presets"], "user_presets": user_presets,
            "fonts": fonts, "hook": data["hook"], "emoji_stems": FALLBACK}


class PresetBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_id: str = "bold-pop"
    style: dict[str, Any]


@router.post("/presets", status_code=201)
def save_preset(body: PresetBody, db: DB, user: CurrentUser) -> dict[str, Any]:
    from app.pipeline.presets import resolve_style

    base = body.base_id if body.base_id in builtin_ids() else "bold-pop"
    full = resolve_style(base, body.style)  # store the complete style (self-contained)
    p = Preset(user_id=user.id, name=body.name.strip(), base_id=base, style=sanitize_style(full))
    db.add(p)
    db.commit()
    return {"id": f"user:{p.id}", "name": p.name, "base_id": p.base_id, "style": p.style, "custom": True}


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: str, db: DB, user: CurrentUser) -> dict[str, bool]:
    pid = preset_id.removeprefix("user:")
    p = db.get(Preset, pid)
    if p is None or p.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Preset nenalezen.")
    db.delete(p)
    db.commit()
    return {"ok": True}


# ---- fonts ----------------------------------------------------------------------

@router.get("/fonts/builtin/{filename}")
def builtin_font(filename: str) -> FileResponse:
    allowed = {f["file"] for f in load_presets_file()["fonts"]}
    if filename not in allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Font nenalezen.")
    return FileResponse(get_settings().fonts_dir / filename, media_type="font/ttf",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/fonts/user/{font_id}")
def user_font(font_id: str, db: DB, user: CurrentUser) -> FileResponse:
    f = db.get(Font, font_id)
    if f is None or f.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Font nenalezen.")
    media = "font/otf" if f.filename.lower().endswith(".otf") else "font/ttf"
    return FileResponse(get_storage().local_path(f.storage_key), media_type=media)


@router.post("/fonts", status_code=201)
async def upload_font(db: DB, user: CurrentUser, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    from io import BytesIO

    from PIL import ImageFont

    name = file.filename or "font.ttf"
    if not name.lower().endswith((".ttf", ".otf")):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Nahrajte font ve formátu .ttf nebo .otf.")
    data = await file.read(MAX_FONT_BYTES + 1)
    if len(data) > MAX_FONT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Font je příliš velký (max 15 MB).")
    try:
        family, _style = ImageFont.truetype(BytesIO(data), 40).getname()
    except OSError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Soubor není platný font.") from e
    if not family:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Font nemá název rodiny.")
    f = Font(user_id=user.id, family=family, filename=name, storage_key="")
    db.add(f)
    db.flush()
    ext = name.rsplit(".", 1)[-1].lower()
    f.storage_key = f"{user_prefix(user.id)}/fonts/{f.id}.{ext}"
    get_storage().local_path(f.storage_key).write_bytes(data)
    db.commit()
    return {"id": f"user:{f.id}", "label": f"{family} (vlastní)", "family": family, "file": name, "weight": 400,
            "url": f"/api/fonts/user/{f.id}", "custom": True}


@router.delete("/fonts/{font_id}")
def delete_font(font_id: str, db: DB, user: CurrentUser) -> dict[str, bool]:
    f = db.get(Font, font_id.removeprefix("user:"))
    if f is None or f.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Font nenalezen.")
    get_storage().delete(f.storage_key)
    db.delete(f)
    db.commit()
    return {"ok": True}


# ---- brand templates -----------------------------------------------------------------

def brand_out(b: BrandTemplate) -> dict[str, Any]:
    return {
        "id": b.id, "name": b.name, "logo_position": b.logo_position, "logo_opacity": b.logo_opacity,
        "logo_scale": b.logo_scale, "primary_color": b.primary_color, "accent_color": b.accent_color,
        "font_id": b.font_id, "has_logo": bool(b.logo_key), "has_intro": bool(b.intro_key), "has_outro": bool(b.outro_key),
        "logo_url": f"/api/brand-templates/{b.id}/logo" if b.logo_key else None,
    }


@router.get("/brand-templates")
def list_brand(db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    rows = db.scalars(select(BrandTemplate).where(BrandTemplate.user_id == user.id).order_by(BrandTemplate.created_at)).all()
    return [brand_out(b) for b in rows]


async def _save_upload(f: UploadFile, key_base: str, exts: tuple[str, ...], limit: int, what: str) -> str:
    name = (f.filename or "").lower()
    if not name.endswith(exts):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"{what}: nepodporovaný formát ({', '.join(exts)}).")
    ext = name.rsplit(".", 1)[-1]
    key = f"{key_base}.{ext}"
    path = get_storage().local_path(key)
    size = 0
    with open(path, "wb") as out:
        while chunk := await f.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                path.unlink(missing_ok=True)
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{what}: soubor je příliš velký.")
            out.write(chunk)
    return key


@router.post("/brand-templates", status_code=201)
async def create_brand(
    db: DB,
    user: CurrentUser,
    name: Annotated[str, Form(min_length=1, max_length=80)],
    logo_position: Annotated[str, Form()] = "top-right",
    logo_opacity: Annotated[float, Form(ge=0, le=1)] = 0.85,
    logo_scale: Annotated[float, Form(ge=0.03, le=0.6)] = 0.18,
    primary_color: Annotated[str, Form()] = "#FFFFFF",
    accent_color: Annotated[str, Form()] = "#FFD400",
    font_id: Annotated[str | None, Form()] = None,
    logo: Annotated[UploadFile | None, File()] = None,
    intro: Annotated[UploadFile | None, File()] = None,
    outro: Annotated[UploadFile | None, File()] = None,
) -> dict[str, Any]:
    from app.pipeline.presets import normalize_color

    if logo_position not in ("top-left", "top-right", "bottom-left", "bottom-right", "center"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Neplatná pozice loga.")
    b = BrandTemplate(
        user_id=user.id, name=name.strip(), logo_position=logo_position, logo_opacity=logo_opacity,
        logo_scale=logo_scale, primary_color=normalize_color(primary_color, "#FFFFFF"),
        accent_color=normalize_color(accent_color, "#FFD400"), font_id=font_id or None,
    )
    db.add(b)
    db.flush()
    base = f"{user_prefix(user.id)}/brand/{b.id}"
    if logo and logo.filename:
        b.logo_key = await _save_upload(logo, f"{base}/logo", (".png", ".jpg", ".jpeg", ".webp"), MAX_LOGO_BYTES, "Logo")
    for field, up in (("intro_key", intro), ("outro_key", outro)):
        if up and up.filename:
            key = await _save_upload(up, f"{base}/{field[:5]}", (".mp4", ".mov", ".webm", ".mkv"), MAX_BUMPER_BYTES, "Intro/outro")
            from app.pipeline.media import MediaError, probe

            try:
                probe(get_storage().local_path(key))
            except MediaError as e:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Intro/outro: {e}") from e
            setattr(b, field, key)
    db.commit()
    return brand_out(b)


@router.get("/brand-templates/{brand_id}/logo")
def brand_logo(brand_id: str, db: DB, user: CurrentUser) -> FileResponse:
    b = db.get(BrandTemplate, brand_id)
    if b is None or b.user_id != user.id or not b.logo_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Logo nenalezeno.")
    return FileResponse(get_storage().local_path(b.logo_key))


@router.delete("/brand-templates/{brand_id}")
def delete_brand(brand_id: str, db: DB, user: CurrentUser) -> dict[str, bool]:
    b = db.get(BrandTemplate, brand_id)
    if b is None or b.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brand template nenalezena.")
    get_storage().delete_prefix(f"{user_prefix(user.id)}/brand/{b.id}")
    db.delete(b)
    db.commit()
    return {"ok": True}


# ---- system / settings -----------------------------------------------------------------

@router.get("/system")
def system_info(user: CurrentUser) -> dict[str, Any]:
    s = get_settings()
    out: dict[str, Any] = {**s.public_dict()}
    try:
        provider = get_provider()
        status_ = provider.check()
    except LLMConfigError as e:
        status_ = {"ok": False, "message": str(e)}
    out["llm_status"] = status_
    if s.llm_provider == "anthropic":
        out["cost_per_hour"] = {
            m: {"cs": estimate_hour(m, "cs", s.llm_window_minutes, s.llm_window_overlap_minutes),
                "en": estimate_hour(m, "en", s.llm_window_minutes, s.llm_window_overlap_minutes)}
            for m in ("claude-haiku-5-5", "claude-sonnet-5-5")
        }
        cur = s.anthropic_model
        out["current_cost_per_hour"] = {
            "cs": estimate_hour(cur, "cs", s.llm_window_minutes, s.llm_window_overlap_minutes),
            "en": estimate_hour(cur, "en", s.llm_window_minutes, s.llm_window_overlap_minutes),
        }
        out["prices"] = {m: {"input": p[0], "output": p[1]} for m, p in PRICES.items()}
    _ = user
    return out
