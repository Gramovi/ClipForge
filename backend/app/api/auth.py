from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.config import get_settings
from app.models import User
from app.security import COOKIE_NAME, create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


def _set_cookie(resp: Response, user_id: str) -> None:
    s = get_settings()
    resp.set_cookie(
        COOKIE_NAME, create_token(user_id), httponly=True, samesite="lax", secure=s.cookie_secure,
        max_age=s.session_days * 86400, path="/",
    )


def _user_out(u: User) -> dict[str, str]:
    return {"id": u.id, "email": u.email}


@router.post("/register", status_code=201)
def register(body: Credentials, db: DB, response: Response) -> dict[str, str]:
    if not get_settings().allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registrace jsou vypnuté.")
    email = body.email.lower().strip()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Účet s tímto e-mailem už existuje.")
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    _set_cookie(response, user.id)
    return _user_out(user)


@router.post("/login")
def login(body: LoginBody, db: DB, response: Response) -> dict[str, str]:
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower().strip()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nesprávný e-mail nebo heslo.")
    _set_cookie(response, user.id)
    return _user_out(user)


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser) -> dict[str, str]:
    return _user_out(user)
