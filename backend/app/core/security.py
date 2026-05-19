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

Multi-tenancy (per contract H-3):
  ``create_access_token()`` accepts an optional ``tenant_id`` kwarg
  that is embedded as a JWT claim. Phase 1 callers may omit it
  (defaults to 1 = CPMAI per BC-2). Phase 2 will populate it from
  the authenticated user's tenant. Old JWTs without the claim
  continue to decode normally; readers should default missing
  ``tenant_id`` to 1.
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


def create_access_token(user_id: int, role: str,
                         tenant_id: int | None = None) -> str:
    """Mint a JWT access token.

    Phase 1: tenant_id is OPTIONAL. When omitted, the JWT carries no
    ``tenant_id`` claim — readers default missing claims to 1 (CPMAI)
    per BC-2. This keeps existing call sites untouched.

    Phase 2: every caller passes the authenticated user's tenant_id;
    tenant resolution downstream reads the claim and enforces
    isolation.
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=_access_minutes())).timestamp()),
        "type": "access",
        "jti": secrets.token_urlsafe(16),
    }
    # Only include the claim when explicitly provided so the payload
    # shape for existing Phase 1 callers stays byte-identical.
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int,
                          tenant_id: int | None = None) -> tuple[str, str]:
    """Mint a JWT refresh token. Same tenant_id semantics as access tokens."""
    now = datetime.now(timezone.utc)
    jti = secrets.token_urlsafe(24)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=_refresh_days())).timestamp()),
        "type": "refresh",
        "jti": jti,
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM), jti


def decode_token(token: str) -> dict:
    """Decode and verify a JWT. Returns the payload dict.

    Callers needing tenant_id should use ``payload.get("tenant_id", 1)``
    — old tokens may not carry the claim (per BC-2).
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
