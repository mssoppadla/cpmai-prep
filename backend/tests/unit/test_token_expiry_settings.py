"""Token-lifetime tunability — :mod:`app.core.security`.

JWT access + refresh lifetimes are admin-tunable at runtime via
``settings_store`` keys:

  * ``auth.access_token_expire_minutes`` (default 240, range 5..1440)
  * ``auth.refresh_token_expire_days``   (default 1,   range 1..30)

These tests pin the contract:

  1. With no setting present, lifetimes fall back to env-var defaults
     (``settings.ACCESS_TOKEN_EXPIRE_MINUTES`` / ``REFRESH_TOKEN_EXPIRE_DAYS``)
  2. With a setting present, NEWLY-issued tokens reflect the setting
  3. Out-of-bounds values are defensively clamped — even a corrupted DB
     row (e.g. someone set access=0 directly) can't mint a token that
     immediately expires and breaks every subsequent request.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from jose import jwt

from app.core import security
from app.core.config import settings


def _decode(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[security.JWT_ALGORITHM])


def _ttl_seconds(token: str) -> int:
    payload = _decode(token)
    return payload["exp"] - payload["iat"]


# ---------------------------------------------------------- fallback path

def test_access_token_uses_env_default_when_setting_missing():
    """Setting absent → env-var default is used (240 min by default)."""
    with patch.object(security._store, "get_int",
                      side_effect=lambda key, default: default):
        token = security.create_access_token(user_id=1, role="user")
    assert _ttl_seconds(token) == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_refresh_token_uses_env_default_when_setting_missing():
    """Setting absent → env-var default is used (1 day by default)."""
    with patch.object(security._store, "get_int",
                      side_effect=lambda key, default: default):
        token, _jti = security.create_refresh_token(user_id=1)
    assert _ttl_seconds(token) == settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400


# ---------------------------------------------------------- admin override

def test_admin_can_shrink_access_lifetime_at_runtime():
    """Admin sets ``auth.access_token_expire_minutes = 15`` (compromise
    response) → next token issued has a 15-min TTL, not the 240-min
    default. No restart needed."""
    def fake_get_int(key, default):
        if key == "auth.access_token_expire_minutes":
            return 15
        return default
    with patch.object(security._store, "get_int", side_effect=fake_get_int):
        token = security.create_access_token(user_id=42, role="user")
    assert _ttl_seconds(token) == 15 * 60


def test_admin_can_expand_refresh_lifetime_at_runtime():
    """Admin sets ``auth.refresh_token_expire_days = 14`` (longer
    "remember me" window) → next refresh token TTL reflects it."""
    def fake_get_int(key, default):
        if key == "auth.refresh_token_expire_days":
            return 14
        return default
    with patch.object(security._store, "get_int", side_effect=fake_get_int):
        token, _ = security.create_refresh_token(user_id=42)
    assert _ttl_seconds(token) == 14 * 86400


# ---------------------------------------------------------- defensive clamp

def test_access_clamped_to_min_even_if_setting_is_zero():
    """Direct-DB edit of ``auth.access_token_expire_minutes = 0`` would
    mint a token that's already expired the instant it's issued,
    locking every authed user out. Clamp protects against that — we
    floor at the validator's lower bound (5 minutes)."""
    def fake_get_int(key, default):
        if key == "auth.access_token_expire_minutes":
            return 0
        return default
    with patch.object(security._store, "get_int", side_effect=fake_get_int):
        token = security.create_access_token(user_id=1, role="user")
    assert _ttl_seconds(token) == 5 * 60  # _ACCESS_MIN_MINUTES


def test_access_clamped_to_max_even_if_setting_is_huge():
    """Same defensive clamp on the upper end — a runaway value of
    9999 minutes is capped at the validator ceiling (1440 = 24h)."""
    def fake_get_int(key, default):
        if key == "auth.access_token_expire_minutes":
            return 9999
        return default
    with patch.object(security._store, "get_int", side_effect=fake_get_int):
        token = security.create_access_token(user_id=1, role="user")
    assert _ttl_seconds(token) == 1440 * 60  # _ACCESS_MAX_MINUTES


def test_refresh_clamped_to_min_even_if_setting_is_zero():
    """Refresh lower bound is 1 day — a zero would defeat the whole
    'survive a working day without re-auth' contract."""
    def fake_get_int(key, default):
        if key == "auth.refresh_token_expire_days":
            return 0
        return default
    with patch.object(security._store, "get_int", side_effect=fake_get_int):
        token, _ = security.create_refresh_token(user_id=1)
    assert _ttl_seconds(token) == 1 * 86400  # _REFRESH_MIN_DAYS


def test_refresh_clamped_to_max_even_if_setting_is_huge():
    """Refresh upper bound is 30 days — caps the long-tail risk of a
    stolen refresh-token usability window."""
    def fake_get_int(key, default):
        if key == "auth.refresh_token_expire_days":
            return 365
        return default
    with patch.object(security._store, "get_int", side_effect=fake_get_int):
        token, _ = security.create_refresh_token(user_id=1)
    assert _ttl_seconds(token) == 30 * 86400  # _REFRESH_MAX_DAYS


# ---------------------------------------------------------- carry-over note

def test_change_does_not_invalidate_already_issued_tokens():
    """Documentation contract: existing tokens carry their own exp
    claim. Changing the setting affects only NEWLY-issued tokens —
    tokens already in the wild continue working until self-expiry.
    To force-logout everyone, rotate SECRET_KEY."""
    # Issue with default (240 min)
    with patch.object(security._store, "get_int",
                      side_effect=lambda key, default: default):
        old_token = security.create_access_token(user_id=99, role="user")
    old_ttl = _ttl_seconds(old_token)
    assert old_ttl == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    # Now admin shrinks it
    def fake_get_int(key, default):
        if key == "auth.access_token_expire_minutes":
            return 5
        return default
    with patch.object(security._store, "get_int", side_effect=fake_get_int):
        new_token = security.create_access_token(user_id=99, role="user")
    # New token reflects new setting, old token is unchanged.
    assert _ttl_seconds(new_token) == 5 * 60
    assert _ttl_seconds(old_token) == old_ttl  # unchanged

    # And the old token still decodes successfully (until its own exp).
    decoded = _decode(old_token)
    assert decoded["sub"] == "99"
