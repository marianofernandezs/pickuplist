from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import secrets
import re

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import PasswordResetToken, User
from app.security import verify_password


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    user: User | None


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_email_allowed(email: str) -> bool:
    if not settings.auth_allowed_emails:
        return True
    return normalize_email(email) in set(settings.auth_allowed_emails)


def authenticate_user(db: Session, email: str, password: str) -> AuthResult:
    normalized = normalize_email(email)
    user = db.query(User).filter(User.email == normalized).first()
    if user is None:
        return AuthResult(ok=False, user=None)
    if not user.is_active:
        return AuthResult(ok=False, user=None)
    if not is_email_allowed(normalized):
        return AuthResult(ok=False, user=None)
    if not verify_password(password, user.hashed_password):
        return AuthResult(ok=False, user=None)
    return AuthResult(ok=True, user=user)


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_password_reset_token(db: Session, user: User) -> str:
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).delete()

    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_reset_token(raw_token)
    expires_at = datetime.utcnow() + timedelta(minutes=settings.auth_password_reset_expire_minutes)

    entity = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        used_at=None,
    )
    db.add(entity)
    db.commit()
    return raw_token


def consume_password_reset_token(db: Session, raw_token: str) -> User | None:
    token_hash = _hash_reset_token(raw_token)
    token = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()
    if token is None:
        return None
    if token.used_at is not None:
        return None
    if token.expires_at < datetime.utcnow():
        return None

    user = db.query(User).filter(User.id == token.user_id).first()
    if user is None or not user.is_active:
        return None

    token.used_at = datetime.utcnow()
    db.add(token)
    db.commit()
    return user


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("La contraseña debe incluir al menos una letra mayúscula.")
    if not re.search(r"[a-z]", password):
        raise ValueError("La contraseña debe incluir al menos una letra minúscula.")
    if not re.search(r"[0-9]", password):
        raise ValueError("La contraseña debe incluir al menos un número.")
