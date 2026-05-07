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


def get_actor(
    authorization: str | None = Header(default=None),
    x_anon_token: str | None = Header(default=None, alias="X-Anon-Token"),
    db: Session = Depends(get_db),
) -> "User | str | None":
    """Resolve the request actor for endpoints that allow either a signed-in
    user OR an anonymous browser-bound token (free exam attempts).

    Returns:
        User instance — if a valid bearer token is present
        str (the X-Anon-Token value) — if no auth but the client supplies an
            anonymous identifier; opaque to the backend, just used for session
            ownership checks
        None — if neither is present (caller decides how to handle)
    """
    payload = _decode_bearer(authorization)
    if payload:
        user = db.get(User, int(payload["sub"]))
        if user and user.is_active:
            return user
    if x_anon_token and 8 <= len(x_anon_token) <= 64:
        return x_anon_token
    return None


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise ForbiddenError("Admin access required")
    return user


def get_super_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise ForbiddenError("Super-admin access required")
    return user
