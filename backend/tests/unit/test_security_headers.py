"""Pin the CSP behaviour the middleware promises.

History: a previous ``default-src 'none'`` was applied to every
response, including the FastAPI ``/docs`` page. Swagger UI loads its
JS/CSS from ``cdn.jsdelivr.net``, which the strict policy blocks, so
``/docs`` rendered blank in browsers — making the dev API explorer
unusable. The middleware is now path-aware: strict CSP on the actual
API responses, permissive (but bounded) CSP on the docs paths.

These tests guard against:

  1. The strict policy being silently weakened on real endpoints
     (would defeat the XSS / sniff defenses).
  2. The strict policy being re-applied to ``/docs`` (would re-break
     the dev API explorer).
  3. ``frame-ancestors 'none'`` being dropped anywhere (clickjacking).
  4. Other security headers (HSTS, X-Frame-Options, etc.) staying on
     every response.

In production, ``docs_url`` is forced to ``None`` so the docs paths
return 404 — these tests assume the test env (``APP_ENV=test``) where
the docs are enabled.
"""
from __future__ import annotations


# ----------------------------------------------------- strict CSP on API

def test_api_endpoint_has_strict_default_src_none(client):
    """Any real API response must carry ``default-src 'none'`` — no
    cross-origin script/style/image loading from API JSON pages."""
    r = client.get("/api/v1/health")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'none'" in csp, csp
    assert "frame-ancestors 'none'" in csp, csp
    # And nothing else permissive snuck in
    assert "cdn.jsdelivr.net" not in csp


def test_auth_endpoint_has_strict_csp_even_on_401(client):
    """Strict CSP applies to error responses too (a 401/422 must not
    be more permissive than a 200)."""
    r = client.get("/api/v1/users/me")  # no auth header → 401
    assert r.status_code == 401
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'none'" in csp, csp


def test_admin_endpoint_strict_csp_on_403(client, user):
    """Forbidden responses also carry the strict CSP."""
    from tests.conftest import auth_header
    r = client.get("/api/v1/admin/content-pages",
                   headers=auth_header(client, user.email))
    assert r.status_code == 403
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'none'" in csp, csp


# ----------------------------------------------------- permissive CSP on /docs

def test_docs_path_has_permissive_csp(client):
    """``/docs`` (Swagger UI) must allow cdn.jsdelivr.net so the UI
    actually renders — otherwise the dev API explorer is blank."""
    r = client.get("/docs")
    assert r.status_code == 200
    csp = r.headers.get("Content-Security-Policy", "")
    # Strict directive must NOT be present on this path
    assert "default-src 'none'" not in csp, csp
    # Swagger UI's CDN must be allowed for both scripts and styles
    assert "cdn.jsdelivr.net" in csp, csp
    assert "script-src" in csp and "style-src" in csp
    # Clickjacking defense kept
    assert "frame-ancestors 'none'" in csp, csp


def test_redoc_path_has_permissive_csp(client):
    """ReDoc also loads from cdn.jsdelivr.net and needs the same relief."""
    r = client.get("/redoc")
    assert r.status_code == 200
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'none'" not in csp, csp
    assert "cdn.jsdelivr.net" in csp, csp


def test_openapi_json_has_strict_csp(client):
    """The OpenAPI schema itself is JSON — it's not a UI surface, so
    it gets the strict policy. The Swagger page (which fetches this)
    has ``connect-src 'self'`` in its own permissive CSP to allow the
    fetch."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'none'" in csp, csp


# ----------------------------------------------------- other headers stay everywhere

def test_other_security_headers_present_on_api(client):
    r = client.get("/api/v1/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in r.headers["Permissions-Policy"]
    assert r.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert r.headers["Strict-Transport-Security"].startswith("max-age=63072000")


def test_other_security_headers_present_on_docs(client):
    """The permissive CSP relief is ONLY for the CSP header. Every
    other security header must still be on /docs."""
    r = client.get("/docs")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cross-Origin-Opener-Policy"] == "same-origin"
