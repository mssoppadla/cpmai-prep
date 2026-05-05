"""Auth endpoints: signup, login, refresh, logout."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from app.core.config import settings
from app.core.deps import get_db, get_current_user
from app.core.security import JWT_ALGORITHM
from app.core.redis import redis_client
from app.core.exceptions import UnauthorizedError, ConflictError
from app.main import limiter
from app.models.user import User
from app.schemas.auth import (
    SignupIn, LoginIn, RefreshIn, AuthTokens, RefreshOut, UserOut,
)
from app.services.auth_service import AuthService
from app.services.tracking_service import emit_event

router = APIRouter()


def _ctx(request: Request) -> dict:
    return {
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent", "")[:255],
        "request_id": getattr(request.state, "request_id", None),
    }


@router.post("/signup", response_model=AuthTokens, status_code=201)
@limiter.limit("3/minute")
def signup(payload: SignupIn, request: Request, db: Session = Depends(get_db)):
    svc = AuthService(db)
    user, access, refresh = svc.signup(payload.email, payload.password,
                                        payload.name, _ctx(request))
    emit_event(db, "auth.signup", user_id=user.id,
               anon_id=getattr(request.state, "anon_id", None),
               session_id=getattr(request.state, "session_id", None))
    return AuthTokens(access=access, refresh=refresh, user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthTokens)
@limiter.limit("5/minute")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    svc = AuthService(db)
    user, access, refresh = svc.login(payload.email, payload.password, _ctx(request))
    emit_event(db, "auth.login", user_id=user.id)
    return AuthTokens(access=access, refresh=refresh, user=UserOut.model_validate(user))


@router.post("/refresh", response_model=RefreshOut)
def refresh(payload: RefreshIn, db: Session = Depends(get_db)):
    try:
        decoded = jwt.decode(payload.refresh_token, settings.SECRET_KEY,
                             algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise UnauthorizedError("Invalid refresh token")
    if decoded.get("type") != "refresh":
        raise UnauthorizedError("Wrong token type")
    jti = decoded.get("jti")
    if not jti or not redis_client.exists(f"refresh:{jti}"):
        raise UnauthorizedError("Refresh token revoked")
    user = db.get(User, int(decoded["sub"]))
    if not user or not user.is_active:
        raise UnauthorizedError()
    # Rotate
    AuthService(db).logout(jti)
    access, new_refresh = AuthService(db)._issue(user)
    return RefreshOut(access=access, refresh=new_refresh)


@router.post("/logout", status_code=204)
def logout(request: Request, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            decoded = jwt.decode(auth.split(" ", 1)[1], settings.SECRET_KEY,
                                 algorithms=[JWT_ALGORITHM])
            jti = decoded.get("jti")
            if jti:
                AuthService(db).logout(jti)
        except JWTError:
            pass
    return
