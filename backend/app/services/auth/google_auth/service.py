"""GoogleAuthService — orchestrates verify → provision.

Token issuance is intentionally NOT part of this module — every project
issues its own session tokens differently (JWT vs cookie session vs
NextAuth backend etc.). Use this to authenticate; then call your own
token issuer.
"""
from __future__ import annotations

from .config import GoogleAuthConfig
from .provisioner import GoogleClaims, UserProvisioner
from .verifier import TokenVerificationError, verify_google_id_token


class GoogleAuthError(Exception):
    """Raised for any failure in the verify+provision pipeline.

    Subclasses preserve the failure category so callers can map to HTTP
    status codes cleanly (401 vs 403 vs 503).
    """


class NotConfiguredError(GoogleAuthError):
    """The module has no client IDs configured — feature is disabled."""


class InvalidTokenError(GoogleAuthError):
    """Token failed verification (signature, expiry, audience, issuer)."""


class AccountInactiveError(GoogleAuthError):
    """Identity verified but the matching local account is disabled."""


class GoogleAuthService:
    """Top-level service. One instance per request is fine; no internal state."""

    def __init__(self, config: GoogleAuthConfig, provisioner: UserProvisioner):
        self.config = config
        self.provisioner = provisioner

    def authenticate(self, credential: str):
        """Verify a Google id_token and return the matching local user.

        Args:
            credential: the `credential` field from Google Sign-In's
                callback (a JWT signed by Google).

        Returns:
            The user object returned by your provisioner.

        Raises:
            NotConfiguredError: no Google client IDs configured.
            InvalidTokenError:  token verification failed.
            AccountInactiveError: matching account exists but is disabled.
        """
        if not self.config.is_configured:
            raise NotConfiguredError(
                "Google sign-in is not configured on this server."
            )

        try:
            claims = verify_google_id_token(
                credential,
                self.config.client_ids,
                require_email_verified=self.config.require_email_verified,
            )
        except TokenVerificationError as e:
            raise InvalidTokenError(str(e)) from e

        try:
            return self.provisioner.find_or_create(GoogleClaims(claims))
        except PermissionError as e:
            raise AccountInactiveError(str(e)) from e
