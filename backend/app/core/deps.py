"""FastAPI dependencies: DB session + current user resolution."""
from fastapi import Depends, Header
from jose import JWTError
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.security import decode_token
from app.core.redis import redis_client
from app.core.exceptions import UnauthorizedError, ForbiddenError
from app.models.user import User, UserRole


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _decode_bearer(authorization: str | None) -> dict | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except JWTError:
        return None
    if payload.get("type") != "access":
        return None
    if redis_client.exists(f"blacklist:{payload.get('jti')}"):
        return None
    return payload


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    payload = _decode_bearer(authorization)
    if not payload:
        raise UnauthorizedError()
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise UnauthorizedError()
    return user


def get_optional_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    payload = _decode_bearer(authorization)
    if not payload:
        return None
    user = db.get(User, int(payload["sub"]))
    return user if user and user.is_active else None


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise ForbiddenError("Admin access required")
    return user


def get_super_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise ForbiddenError("Super-admin access required")
    return user
