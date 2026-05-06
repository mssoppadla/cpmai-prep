"""Reusable Google OAuth ID-token authentication.

Public API — import from this module, not the submodules:

    from app.services.auth.google_auth import (
        GoogleAuthConfig, GoogleAuthService,
        DefaultSqlAlchemyProvisioner,
        GoogleAuthError, NotConfiguredError, InvalidTokenError,
        AccountInactiveError, verify_google_id_token,
    )

Drop-in instructions for another project: see README.md in this directory.
"""
from .config import GoogleAuthConfig
from .provisioner import (
    DefaultSqlAlchemyProvisioner, GoogleClaims, UserProvisioner,
)
from .service import (
    AccountInactiveError, GoogleAuthError, GoogleAuthService,
    InvalidTokenError, NotConfiguredError,
)
from .verifier import TokenVerificationError, verify_google_id_token

__all__ = [
    "GoogleAuthConfig",
    "GoogleAuthService",
    "GoogleAuthError",
    "NotConfiguredError",
    "InvalidTokenError",
    "AccountInactiveError",
    "GoogleClaims",
    "UserProvisioner",
    "DefaultSqlAlchemyProvisioner",
    "verify_google_id_token",
    "TokenVerificationError",
]
