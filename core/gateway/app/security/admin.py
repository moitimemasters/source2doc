from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Request, status

from source2doc.storage.admin_sessions import AdminSession, AdminSessionStorage

from app import config as app_config


COOKIE_NAME = "s2d_admin"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def verify_password(plaintext: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def verify_username(submitted: str, expected: str) -> bool:
    return hmac.compare_digest(submitted.encode(), expected.encode())


async def get_session_storage(request: Request) -> AdminSessionStorage:
    return request.app.state.admin_sessions


async def require_admin(
    s2d_admin: str | None = Cookie(default=None, alias=COOKIE_NAME),
    sessions: AdminSessionStorage = Depends(get_session_storage),
) -> AdminSession:
    if not s2d_admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required",
        )
    session = await sessions.get(hash_token(s2d_admin))
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )
    return session


def session_expiry(config: app_config.Config) -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(hours=config.session_ttl_hours)
