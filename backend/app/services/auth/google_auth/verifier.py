"""Google ID-token verifier — pure, drop-in module.

This file has no app-specific imports. Copy it (and the rest of
google_auth/) into any FastAPI / Flask / Django / standalone Python
project that needs to verify Google Sign-In tokens.

Verification semantics:
    - Signature checked against Google's published JWKS
    - `iss` is `accounts.google.com` (or its https variant)
    - `aud` matches one of the configured client IDs
    - `exp` is in the future
    - `email_verified` is True (configurable)
"""
from __future__ import annotations

from typing import Iterable

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token


_VALID_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class TokenVerificationError(Exception):
    """Raised whenever a Google ID token fails verification.

    Catch this and convert to whatever your framework's auth error is."""


def verify_google_id_token(
    token: str,
    allowed_client_ids: Iterable[str],
    *,
    require_email_verified: bool = True,
) -> dict:
    """Verify a Google-issued OIDC id_token. Returns the verified claims.

    Args:
        token: The raw `credential` from Google Sign-In's callback.
        allowed_client_ids: Every Google OAuth client ID that should be
            accepted as `aud`. Pass multiple if your app is registered
            with both web + mobile clients.
        require_email_verified: When True (default), reject tokens whose
            `email_verified` claim is not True.

    Returns:
        The decoded JWT claims dict, including `sub`, `email`, `name`,
        `picture`, etc.

    Raises:
        TokenVerificationError: signature, expiry, issuer, audience,
            or email-verified check failed.
    """
    allowed = [cid for cid in allowed_client_ids if cid]
    if not allowed:
        raise TokenVerificationError(
            "No client IDs configured — refusing to verify"
        )
    if not token or not isinstance(token, str):
        raise TokenVerificationError("Token is empty or not a string")

    transport = google_requests.Request()

    # google-auth requires us to declare which client_id we expect, but a
    # single backend may serve multiple clients — try each in turn.
    last_err: Exception | None = None
    info: dict | None = None
    for cid in allowed:
        try:
            info = google_id_token.verify_oauth2_token(token, transport, cid)
            break
        except ValueError as e:
            last_err = e
            continue

    if info is None:
        raise TokenVerificationError(
            f"Token rejected by all configured client IDs: {last_err}"
        ) from last_err

    iss = info.get("iss")
    if iss not in _VALID_ISSUERS:
        raise TokenVerificationError(f"Invalid issuer: {iss}")

    if info.get("aud") not in allowed:
        raise TokenVerificationError(
            f"Audience mismatch: aud={info.get('aud')!r} not in {allowed}"
        )

    if require_email_verified and not info.get("email_verified"):
        raise TokenVerificationError("Google account email is not verified")

    return info
