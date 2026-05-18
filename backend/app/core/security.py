"""JWT issuance/verification + Argon2 password hashing.

Token lifetimes are admin-tunable at runtime via the settings_store
(no redeploy needed):

  - ``auth.access_token_expire_minutes``  (default 240, range 5..1440)
  - ``auth.refresh_token_expire_days``    (default 1,   range 1..30)

The env-var defaults in ``Settings`` are the fallback when no row exists
in ``system_settings`` (e.g. on a brand-new install before seeding). Once
seeded, the DB value wins.

Note on revocation: changing a setting affects only NEWLY-issued tokens.
Tokens already in the wild carry their own ``exp`` claim and remain valid
until self-expiry. To force-logout everyone, rotate ``SECRET_KEY``.
"""
import secrets
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings
from app.core.settings_store import SettingsStore

_pwd = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")
_store = SettingsStore()

JWT_ALGORITHM = "HS256"

# Bounds match the validators in ``admin/settings.py``. Defensive clamp here
# protects against a DB row that somehow holds an out-of-bounds value
# (e.g. an admin who edited Postgres directly), so we never mint a
# zero-second token that breaks every subsequent request.
_ACCESS_MIN_MINUTES, _ACCESS_MAX_MINUTES = 5, 1440
_REFRESH_MIN_DAYS,   _REFRESH_MAX_DAYS   = 1, 30


def _access_minutes() -> int:
    v = _store.get_int("auth.access_token_expire_minutes",
                       default=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return max(_ACCESS_MIN_MINUTES, min(_ACCESS_MAX_MINUTES, v))


def _refresh_days() -> int:
    v = _store.get_int("auth.refresh_token_expire_days",
                       default=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return max(_REFRESH_MIN_DAYS, min(_REFRESH_MAX_DAYS, v))


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=_access_minutes())).timestamp()),
        "type": "access",
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    jti = secrets.token_urlsafe(24)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=_refresh_days())).timestamp()),
        "type": "refresh",
        "jti": jti,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM), jti


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
