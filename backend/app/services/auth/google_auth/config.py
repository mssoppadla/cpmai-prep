"""Google auth configuration.

Designed to be loaded once at import time and passed to GoogleAuthService.
The defaults pull from environment variables so the module is plug-and-play
in any project that follows 12-factor config.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


_DEFAULT_ENV_VAR = "GOOGLE_OAUTH_CLIENT_ID"
_EXTRA_ENV_VAR = "GOOGLE_OAUTH_ALLOWED_CLIENT_IDS"  # comma-separated extras


@dataclass(frozen=True)
class GoogleAuthConfig:
    """Configuration for the Google auth module.

    Attributes:
        client_ids: Tuple of accepted `aud` values. Always include the web
            client ID; add mobile/desktop variants if you support them.
        require_email_verified: If True, accounts whose `email_verified`
            claim is False will be rejected.
        default_role: Role assigned to new users created via Google sign-in.
            Existing users keep whatever role they already have — Google
            login never elevates an account.
    """
    client_ids: tuple[str, ...] = field(default_factory=tuple)
    require_email_verified: bool = True
    default_role: str = "user"

    @property
    def is_configured(self) -> bool:
        return bool(self.client_ids)

    @classmethod
    def from_env(cls, *, default_role: str = "user",
                 require_email_verified: bool = True) -> "GoogleAuthConfig":
        """Build config from environment variables.

        Reads:
            GOOGLE_OAUTH_CLIENT_ID            — primary client_id
            GOOGLE_OAUTH_ALLOWED_CLIENT_IDS   — optional CSV of extras
        """
        primary = os.environ.get(_DEFAULT_ENV_VAR, "").strip()
        extras_raw = os.environ.get(_EXTRA_ENV_VAR, "").strip()
        extras = tuple(c.strip() for c in extras_raw.split(",") if c.strip())
        client_ids = (primary,) + extras if primary else extras
        return cls(
            client_ids=client_ids,
            require_email_verified=require_email_verified,
            default_role=default_role,
        )
