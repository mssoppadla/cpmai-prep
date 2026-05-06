"""Auth endpoints: signup, login, refresh, logout, google sign-in."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from app.core.audit import audit_log
from app.core.config import settings
from app.core.deps import get_db, get_current_user
from app.core.exceptions import AppError, UnauthorizedError
from app.core.limiter import limiter
from app.core.security import JWT_ALGORITHM
from app.core.redis import redis_client
from app.models.user import User, UserRole
from app.schemas.auth import (
    SignupIn, LoginIn, GoogleLoginIn, RefreshIn,
    AuthTokens, RefreshOut, UserOut,
)
from app.services.auth_service import AuthService
from app.services.auth.google_auth import (
    AccountInactiveError, DefaultSqlAlchemyProvisioner,
    GoogleAuthConfig, GoogleAuthService,
    InvalidTokenError, NotConfiguredError,
)
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
    emit_event(db, "auth.login", user_id=user.id, metadata={"method": "password"})
    return AuthTokens(access=access, refresh=refresh, user=UserOut.model_validate(user))


@router.post("/google", response_model=AuthTokens)
@limiter.limit("10/minute")
def google_login(payload: GoogleLoginIn, request: Request,
                 db: Session = Depends(get_db)):
    """Sign in with Google. Verifies the ID token, finds-or-creates the
    user, and returns the same access/refresh pair as password login.

    First-time Google users are created with role=`user`. Existing users
    keep their role (admins matched by email retain admin rights)."""
    config = GoogleAuthConfig.from_env()
    if not config.is_configured:
        raise AppError(
            "Google sign-in is not configured on this server.",
            status_code=503,
        )

    provisioner = DefaultSqlAlchemyProvisioner(db, User, UserRole)
    service = GoogleAuthService(config, provisioner)
    try:
        user = service.authenticate(payload.credential)
    except NotConfiguredError as e:
        raise AppError(str(e), status_code=503) from e
    except InvalidTokenError as e:
        raise UnauthorizedError(f"Invalid Google credential: {e}") from e
    except AccountInactiveError as e:
        raise AppError(str(e), status_code=403) from e

    # Provisioner stashes whether this was a new signup, a link, or a login.
    prov = getattr(user, "__google_provisioning__", {})
    ctx = _ctx(request)
    if prov.get("created"):
        audit_log(db, user.id, "auth.signup.google",
                  {"email": user.email}, **ctx)
        emit_event(db, "auth.signup.google", user_id=user.id,
                   request_id=ctx.get("request_id"),
                   metadata={"email": user.email})
    elif prov.get("linked"):
        audit_log(db, user.id, "auth.google.linked",
                  {"email": user.email}, **ctx)
    else:
        audit_log(db, user.id, "auth.login.google",
                  {"email": user.email}, **ctx)

    emit_event(db, "auth.login.google", user_id=user.id,
               request_id=ctx.get("request_id"),
               metadata={"email": user.email,
                         "first_time": bool(prov.get("created"))})

    access, refresh = AuthService(db)._issue(user)
    return AuthTokens(access=access, refresh=refresh,
                      user=UserOut.model_validate(user))


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
    emit_event(db, "auth.logout", user_id=user.id,
               request_id=getattr(request.state, "request_id", None))
    return
