"""Same-origin cookie authentication. Only hashes of opaque tokens reach storage."""

import hashlib
import re
import secrets
import time
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_session
from app.models import Account, LoginBucket, WebSession

router = APIRouter(prefix="/v1/auth", tags=["authentication"])
DB = Annotated[Session, Depends(get_session)]
hasher = PasswordHasher()  # Argon2id; parameters encoded in each hash.
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
COOKIE = "chainlink_session"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_username(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", value):
        raise ValueError(
            "Username must be 3–40 ASCII letters, numbers, dots, underscores or hyphens."
        )
    return value


def create_account(db: Session, username: str, password: str, role: str) -> Account:
    if not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12–256 characters.")
    if role not in {"player", "administrator"}:
        raise ValueError("Invalid role")
    account = Account(
        username=normalize_username(username),
        password_hash=hasher.hash(password),
        role=role,
    )
    db.add(account)
    db.commit()
    return account


def current_session(request: Request, db: Session) -> WebSession | None:
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 128:
        return None
    row = db.get(WebSession, digest(token))
    return row if row and row.expires_at > int(time.time()) else None


def check_csrf(request: Request, row: WebSession | None):
    token = request.cookies.get(COOKIE, "")
    supplied = request.headers.get("x-csrf-token", "")
    if row is None or not secrets.compare_digest(supplied, digest(token + ":csrf")):
        raise HTTPException(
            403, "Invalid or expired security token. Reload and try again."
        )


def administrator(request: Request, db: DB) -> Account:
    row = current_session(request, db)
    account = db.get(Account, row.account_id) if row and row.account_id else None
    if account is None:
        raise HTTPException(401, "Login required")
    if account.role != "administrator":
        raise HTTPException(403, "Administrator permission required")
    check_csrf(request, row)
    return account


def issue_session(response: Response, db: Session, account_id=None) -> str:
    now = int(time.time())
    db.execute(delete(WebSession).where(WebSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    duration = get_settings().session_hours * 3600 if account_id else 1800
    db.add(
        WebSession(
            token_hash=digest(token), account_id=account_id, expires_at=now + duration
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        max_age=duration,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="strict",
        path="/",
    )
    return token


@router.get("/session")
def session_info(request: Request, response: Response, db: DB):
    response.headers["Cache-Control"] = "no-store"
    row = current_session(request, db)
    token = request.cookies.get(COOKIE)
    if row is None:
        token = issue_session(response, db)
    account = db.get(Account, row.account_id) if row and row.account_id else None
    return {
        "user": {"username": account.username, "role": account.role}
        if account
        else None,
        "csrf_token": digest(token + ":csrf"),
    }


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=256)
    password: str = Field(max_length=256)


def throttle(request: Request, db: Session):
    """Atomic fixed-window counter shared by workers. Never trust forwarded IP headers."""
    now = int(time.time())
    window = now // 900
    key = digest(f"{request.client.host if request.client else 'unknown'}:{window}")
    db.execute(delete(LoginBucket).where(LoginBucket.expires_at <= now))
    try:
        with db.begin_nested():
            db.add(LoginBucket(key=key, attempts=0, expires_at=(window + 1) * 900))
            db.flush()
    except IntegrityError:
        pass
    attempts = db.scalar(
        update(LoginBucket)
        .where(LoginBucket.key == key)
        .values(attempts=LoginBucket.attempts + 1)
        .returning(LoginBucket.attempts)
    )
    db.commit()
    if attempts > 10:
        raise HTTPException(
            429,
            "Unable to sign in. Try again later.",
            headers={"Retry-After": str((window + 1) * 900 - now)},
        )


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response, db: DB):
    check_csrf(request, current_session(request, db))
    throttle(request, db)
    account = db.scalar(
        select(Account).where(Account.username == body.username.strip().lower())
    )
    try:
        valid = hasher.verify(
            account.password_hash if account else DUMMY_HASH, body.password
        )
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid or account is None:
        raise HTTPException(401, "Invalid username or password.")
    if hasher.check_needs_rehash(account.password_hash):
        account.password_hash = hasher.hash(body.password)
    # Rotate on every login, including when already signed in.
    db.execute(
        delete(WebSession).where(
            WebSession.token_hash == digest(request.cookies[COOKIE])
        )
    )
    token = issue_session(response, db, account.id)
    response.headers["Cache-Control"] = "no-store"
    return {
        "user": {"username": account.username, "role": account.role},
        "csrf_token": digest(token + ":csrf"),
    }


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DB):
    row = current_session(request, db)
    check_csrf(request, row)
    db.delete(row)
    db.commit()
    response.delete_cookie(
        COOKIE,
        path="/",
        secure=get_settings().session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
