from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.entities import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(email: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.auth_access_token_expire_minutes)
    to_encode = {"sub": email, "exp": expire}
    return jwt.encode(to_encode, settings.auth_jwt_secret_key, algorithm=settings.auth_jwt_algorithm)


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, settings.auth_jwt_secret_key, algorithms=[settings.auth_jwt_algorithm])
        email = payload.get("sub")
        if not isinstance(email, str):
            raise _credentials_exception()
    except JWTError as exc:
        raise _credentials_exception() from exc

    user = db.query(User).filter(User.email == email.lower()).first()
    if user is None:
        raise _credentials_exception()
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo.")
    return user
