"""Standard security headers — applied to every response.

The Content-Security-Policy is path-aware:

  * **API responses** (everything except the docs paths) get the strict
    ``default-src 'none'`` policy — these are pure JSON endpoints that
    must never load anything cross-origin. Defends against XSS-style
    abuse of content-type sniffing.

  * **FastAPI auto-generated docs** (``/docs``, ``/redoc``,
    ``/docs/oauth2-redirect``) need a more permissive policy because
    FastAPI's stock UI loads Swagger UI / ReDoc assets from
    ``cdn.jsdelivr.net``. With the strict policy applied to these
    paths, the JS/CSS never loads and the page renders blank —
    making the API explorer unusable in local dev (browser console
    shows "Refused to load... default-src 'none'").

In production, ``docs_url`` is forced to ``None`` in ``app/main.py``,
so the docs paths return 404 there and the permissive branch is never
taken. The strict policy still applies to every real API response.

``frame-ancestors 'none'`` (clickjacking defense) is kept on every path,
including the docs paths.
"""
from starlette.middleware.base import BaseHTTPMiddleware


# Paths served by FastAPI's auto-docs. Keep this set explicit — adding a
# wildcard would accidentally relax CSP on user-facing paths.
_DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})


# Strict policy for actual API responses. Pure JSON — nothing to load.
_CSP_STRICT = "default-src 'none'; frame-ancestors 'none'"


# Permissive policy for Swagger UI / ReDoc. cdn.jsdelivr.net is FastAPI's
# default CDN for both UIs; ``'unsafe-inline'`` is required because
# Swagger UI emits inline <script> + <style> blocks to bootstrap itself.
# ``worker-src 'self' blob:`` is required by ReDoc for its syntax
# highlighting web worker. ``connect-src 'self'`` lets the UI fetch
# ``/openapi.json`` from the same origin.
_CSP_DOCS = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://cdn.jsdelivr.net https://fastapi.tiangolo.com; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        # Path-aware CSP: strict for API, permissive for FastAPI docs UI.
        resp.headers["Content-Security-Policy"] = (
            _CSP_DOCS if request.url.path in _DOCS_PATHS else _CSP_STRICT
        )
        return resp
