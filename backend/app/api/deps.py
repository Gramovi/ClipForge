"""Shared API dependencies: current user and ownership-checked lookups."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Clip, Project, User
from app.security import COOKIE_NAME, decode_token

DB = Annotated[Session, Depends(get_db)]


def current_user(db: DB, cf_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None) -> User:
    uid = decode_token(cf_session) if cf_session else None
    user = db.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nejste přihlášeni.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def owned_project(db: Session, user: User, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if p is None or p.user_id != user.id:  # never reveal other users' data
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projekt nenalezen.")
    return p


def owned_clip(db: Session, user: User, clip_id: str) -> Clip:
    c = db.get(Clip, clip_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Klip nenalezen.")
    return c
