"""Unit tests for signed media tokens + the mint boundary.

These guard the security contract for paid media: tokens are bound to a
specific path, expire, and can't be forged or replayed as auth tokens.
"""
from __future__ import annotations

import pytest

from app.core.media_tokens import (
    is_public_image, protected_media_url, sign_media_token, verify_media_token,
)
from app.core.security import create_access_token


REL = "1/2026/06/abc123-lecture.mp4"


def test_sign_verify_round_trip():
    tok = sign_media_token(REL, user_id=7)
    claims = verify_media_token(tok)
    assert claims is not None
    assert claims["path"] == REL
    assert claims["sub"] == "7"
    assert claims["type"] == "media"


def test_expired_token_rejected():
    tok = sign_media_token(REL, user_id=7, ttl_seconds=-10)  # already expired
    assert verify_media_token(tok) is None


def test_tampered_token_rejected():
    tok = sign_media_token(REL, user_id=7)
    # Flip a character in the signature segment.
    head, payload, sig = tok.split(".")
    bad = f"{head}.{payload}.{sig[:-2]}xx"
    assert verify_media_token(bad) is None


def test_garbage_token_rejected():
    assert verify_media_token("not-a-jwt") is None
    assert verify_media_token("") is None


def test_access_token_not_accepted_as_media_token():
    # An auth access token decodes with the same secret but has the wrong
    # type — it must NOT be usable to fetch protected media.
    access = create_access_token(user_id=7, role="user")
    assert verify_media_token(access) is None


@pytest.mark.parametrize("name,expected", [
    ("a.png", True), ("a.JPG", True), ("a.jpeg", True), ("a.gif", True),
    ("a.webp", True), ("a.svg", True), ("a.avif", True),
    ("a.mp4", False), ("a.pdf", False), ("a.webm", False), ("a.mp3", False),
    ("noext", False),
])
def test_is_public_image(name, expected):
    assert is_public_image(name) is expected


def test_protected_media_url_passthrough_for_external_and_image():
    assert protected_media_url(None, 1) is None
    assert protected_media_url("", 1) == ""
    assert protected_media_url("https://youtu.be/x", 1) == "https://youtu.be/x"
    assert protected_media_url("/uploads/1/2026/06/pic.png", 1) == \
        "/uploads/1/2026/06/pic.png"


def test_protected_media_url_signs_non_image():
    signed = protected_media_url(f"/uploads/{REL}", user_id=9)
    assert signed.startswith(f"/uploads/{REL}?token=")
    token = signed.split("token=", 1)[1]
    claims = verify_media_token(token)
    assert claims is not None
    # Token is bound to exactly the requested path.
    assert claims["path"] == REL
    assert claims["sub"] == "9"
