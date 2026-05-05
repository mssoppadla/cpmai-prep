"""Authentication service: signup, login (with lockout), token issuance."""
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.core.security import (
    hash_password, verify_password, create_access_token, create_refresh_token
)
from app.core.redis import redis_client
from app.core.audit import audit_log
from app.core.settings_store import settings_store
from app.core.exceptions import (
    AccountLockedError, InvalidCredentialsError, ConflictError
)
from app.models.user import User, UserRole


REFRESH_TTL_SECONDS = 60 * 60 * 24 * 7


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def signup(self, email: str, password: str, name: str | None,
               request_ctx: dict) -> tuple[User, str, str]:
        email = email.lower()
        if self.db.query(User).filter_by(email=email).first():
            raise ConflictError("An account with that email already exists.")
        user = User(email=email, password_hash=hash_password(password), name=name)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        audit_log(self.db, user.id, "auth.signup", **request_ctx)
        access, refresh = self._issue(user)
        return user, access, refresh

    def login(self, email: str, password: str, request_ctx: dict
              ) -> tuple[User, str, str]:
        email = email.lower()
        user = self.db.query(User).filter_by(email=email).first()
        if not user:
            raise InvalidCredentialsError()

        if user.locked_until and user.locked_until > datetime.now(timezone.utc):
            raise AccountLockedError(user.locked_until)

        if not verify_password(password, user.password_hash):
            user.failed_login_count += 1
            threshold = settings_store.get_int("auth.lockout_threshold", 5)
            if user.failed_login_count >= threshold:
                minutes = settings_store.get_int("auth.lockout_minutes", 15)
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
                user.failed_login_count = 0
            self.db.commit()
            audit_log(self.db, user.id, "auth.login.failed", **request_ctx)
            raise InvalidCredentialsError()

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()
        audit_log(self.db, user.id, "auth.login.success", **request_ctx)
        access, refresh = self._issue(user)
        return user, access, refresh

    def logout(self, jti: str, exp_seconds: int = REFRESH_TTL_SECONDS):
        try:
            redis_client.delete(f"refresh:{jti}")
            redis_client.setex(f"blacklist:{jti}", exp_seconds, "1")
        except Exception:
            pass

    def _issue(self, user: User) -> tuple[str, str]:
        access = create_access_token(user.id, user.role.value)
        refresh, jti = create_refresh_token(user.id)
        try:
            redis_client.setex(f"refresh:{jti}", REFRESH_TTL_SECONDS, str(user.id))
        except Exception:
            pass
        return access, refresh
