"""SQLAlchemy ORM models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    projects: Mapped[list[Project]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Upload(Base):
    """A resumable chunked upload session."""

    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    size: Mapped[int] = mapped_column(BigInteger)
    received: Mapped[int] = mapped_column(BigInteger, default=0)
    storage_key: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="uploading")  # uploading|complete|used
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|processing|done|failed
    step: Mapped[str] = mapped_column(String(30), default="upload")
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # overall 0..100
    step_progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..100 within step
    eta_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    source_type: Mapped[str] = mapped_column(String(10), default="upload")  # upload|url
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    llm_usage: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    thumbnail_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transcript_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="projects")
    clips: Mapped[list[Clip]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Clip.virality_score.desc()"
    )


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(300))
    hook: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSONType, default=list)
    scores: Mapped[dict[str, float]] = mapped_column(JSONType, default=dict)
    virality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    # per-clip edits: aspect, preset_id, style overrides, layout, text edits, hook, silence/filler removal
    edit: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    analysis_key: Mapped[str | None] = mapped_column(String(500), nullable=True)  # face track JSON
    preview_key: Mapped[str | None] = mapped_column(String(500), nullable=True)  # raw source excerpt
    preview_offset: Mapped[float] = mapped_column(Float, default=0.0)  # source time at preview t=0
    video_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thumb_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    srt_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    render_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|queued|rendering|ready|failed
    render_progress: Mapped[float] = mapped_column(Float, default=0.0)
    render_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    render_info: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    dirty: Mapped[bool] = mapped_column(Boolean, default=False)  # edited since last render
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    project: Mapped[Project] = relationship(back_populates="clips")


class Preset(Base):
    """User-saved caption preset (full style JSON)."""

    __tablename__ = "presets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    base_id: Mapped[str] = mapped_column(String(50))
    style: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BrandTemplate(Base):
    __tablename__ = "brand_templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    logo_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    logo_position: Mapped[str] = mapped_column(String(20), default="top-right")
    logo_opacity: Mapped[float] = mapped_column(Float, default=0.85)
    logo_scale: Mapped[float] = mapped_column(Float, default=0.18)  # fraction of output width
    primary_color: Mapped[str] = mapped_column(String(9), default="#FFFFFF")
    accent_color: Mapped[str] = mapped_column(String(9), default="#FFD400")
    font_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intro_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    outro_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Font(Base):
    """User-uploaded font file."""

    __tablename__ = "fonts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(300))
    storage_key: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExportJob(Base):
    """ZIP export of all clips in a project."""

    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|ready|failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    zip_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
