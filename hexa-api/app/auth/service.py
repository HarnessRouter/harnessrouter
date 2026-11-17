from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.auth.passwords import verify_password
from app.config import Settings
from app.db.models import AuthSession


COOKIE_NAME = "hexa_session"


def _token_hash(token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def authenticate(settings: Settings, username: str, password: str) -> bool:
    password_ok = verify_password(password, settings.admin_password_hash)
    return secrets.compare_digest(username.encode(), settings.admin_username.encode()) and password_ok


def create_session(db: Session, settings: Settings, username: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.add(AuthSession(token_hash=_token_hash(token, settings.session_secret), username=username, created_at=now, expires_at=now + timedelta(seconds=settings.session_ttl_seconds)))
    db.commit()
    return token


def get_session(db: Session, token: str | None, secret: str) -> AuthSession | None:
    if not token:
        return None
    record = db.query(AuthSession).filter(AuthSession.token_hash == _token_hash(token, secret), AuthSession.revoked.is_(False)).one_or_none()
    if record is None:
        return None
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return None
    return record
