"""User provisioner — pluggable interface for find-or-create logic.

The verifier returns Google's claims; we still need to map a verified
identity onto a user row in *your* database. Different projects have
different User models, so we expose this as a Protocol that you
implement once per project.

A default SQLAlchemy implementation is provided that targets the
canonical User model in this repo. To use this module in another
project, write your own implementation of `UserProvisioner` and pass
it to `GoogleAuthService`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class GoogleClaims:
    """Lightweight, framework-agnostic view of the verified Google claims.

    Defined as a class only so type-checkers can see the fields. Build it
    from the dict returned by `verify_google_id_token`.
    """
    def __init__(self, claims: dict):
        self.sub: str = claims["sub"]
        self.email: str = (claims.get("email") or "").lower().strip()
        self.email_verified: bool = bool(claims.get("email_verified"))
        self.name: str | None = claims.get("name")
        self.picture: str | None = claims.get("picture")
        self.raw: dict = claims


class UserProvisioner(Protocol):
    """Find or create a user row from a verified Google identity.

    Return value is whatever your project uses to represent a user. The
    GoogleAuthService is generic over this type — it only requires that
    the returned object has an `id`, `email`, and `role` attribute (so it
    can be passed to the project's existing token-issuing code).
    """
    def find_or_create(self, claims: GoogleClaims) -> object: ...


# -----------------------------------------------------------------------------
# Default implementation for this project's User model.
# -----------------------------------------------------------------------------
class DefaultSqlAlchemyProvisioner:
    """Find-or-create against this repo's User model.

    Lookup order:
        1. by `google_id` — already-linked Google accounts log in instantly
        2. by `email` — links Google to an existing password account
           (preserving its role; admins keep their admin role)
        3. otherwise create a new row with role=default_role, no password

    The contract: existing users never change role on Google login. Admins
    who linked their personal Google retain their admin status; Google
    cannot elevate a regular user to admin.
    """

    def __init__(self, db_session, user_model, role_enum,
                 default_role: str = "user"):
        self.db = db_session
        self.User = user_model
        self.UserRole = role_enum
        self.default_role = default_role

    def find_or_create(self, claims: GoogleClaims):
        # 1. Match on google_id (cheapest, deterministic)
        user = self.db.query(self.User).filter_by(google_id=claims.sub).first()
        created = False
        linked = False

        if user is None:
            # 2. Match on email — link Google to an existing account
            user = self.db.query(self.User).filter_by(email=claims.email).first()
            if user is not None:
                user.google_id = claims.sub
                linked = True
            else:
                # 3. New user — first time seeing this Google account
                user = self.User(
                    email=claims.email,
                    google_id=claims.sub,
                    name=claims.name or claims.email.split("@")[0],
                    password_hash=None,
                    role=self.UserRole(self.default_role),
                    is_active=True,
                )
                self.db.add(user)
                created = True

        if not user.is_active:
            raise PermissionError("Account is disabled")

        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user)

        # Stash provisioning result on the object — useful for the caller
        # to emit different audit events for created vs. linked vs. login.
        user.__google_provisioning__ = {
            "created": created, "linked": linked, "login": not (created or linked),
        }
        return user
