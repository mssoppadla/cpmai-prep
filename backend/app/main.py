"""FastAPI entrypoint with full middleware stack and exception handling.

Where unhandled-exception 500s come from
----------------------------------------
The fallback handler for uncaught exceptions lives in
``RequestLoggingMiddleware`` (``app/core/middleware/logging_mw.py``)
rather than as a ``@app.exception_handler(Exception)`` here. The reason:
``BaseHTTPMiddleware`` task-group semantics cause exceptions to bypass
FastAPI's ``ExceptionMiddleware`` before any ``@app.exception_handler``
can match them. Catching in the logging middleware ensures the response
still propagates back through ``CORSMiddleware`` — so the browser sees
a proper JSON 500 with the right CORS headers instead of a bare 500
that looks like a network failure.

See the docstring on ``RequestLoggingMiddleware`` for the full
rationale.
"""
import threading
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.exceptions import RequestValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.exceptions import AppError
from app.core.settings_store import start_invalidation_listener
from app.core.middleware.correlation import CorrelationMiddleware
from app.core.middleware.security_headers import SecurityHeadersMiddleware
from app.core.middleware.logging_mw import RequestLoggingMiddleware
from app.core.limiter import limiter
from app.api.v1.router import api_router

configure_logging()

app = FastAPI(
    title="CPMAI Prep API",
    version="0.4.0",
    docs_url="/docs" if settings.APP_ENV != "production" else None,
)
app.state.limiter = limiter

# Middleware (outermost first)
# Internal docker service hostnames are always allowed in addition to the
# public ALLOWED_HOSTS: the frontend proxies /uploads/* to this service via a
# Next.js rewrite (so lesson videos / CMS images served by StaticFiles are
# reachable behind the "/"→frontend reverse proxy). That proxied request
# carries Host: backend (the compose service name), which isn't a public
# domain — without this it 400s "Invalid host header". Only reachable inside
# the compose network. (Starlette strips the port before matching.)
_INTERNAL_HOSTS = ["backend", "localhost", "127.0.0.1"]
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=(settings.ALLOWED_HOSTS or ["*"]) + _INTERNAL_HOSTS,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CorrelationMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type",
                   "X-Request-ID", "X-Session-ID",
                   "X-Anon-ID", "X-Anon-Token",
                   "X-Razorpay-Signature"],
    expose_headers=["X-Request-ID", "X-Total-Count",
                    "X-Chat-Quota-Used", "X-Chat-Quota-Limit",
                    "X-Chat-Quota-Remaining", "X-Chat-Quota-Reset"],
    max_age=600,
)

# Exception handlers — every error follows the contract
@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError):
    body = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    body["request_id"] = getattr(request.state, "request_id", None)
    return JSONResponse(status_code=exc.status_code, content={"error": body})


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    fields = {}
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"][1:])
        fields[loc or err["loc"][0]] = err["msg"]
    return JSONResponse(status_code=422, content={"error": {
        "code": "validation_failed",
        "message": "One or more fields failed validation.",
        "fields": fields,
        "request_id": getattr(request.state, "request_id", None),
    }})


@app.exception_handler(RateLimitExceeded)
async def handle_rate_limit(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"error": {
        "code": "rate_limited",
        "message": "Too many requests. Please slow down.",
        "request_id": getattr(request.state, "request_id", None),
    }})


@app.exception_handler(IntegrityError)
async def handle_integrity_error(request: Request, exc: IntegrityError):
    """Catch DB-level uniqueness/FK violations and return a clean 409.

    Endpoints SHOULD pre-check uniqueness so the user gets a field-named
    message ("Slug 'foo' already in use"), but races and missed checks
    happen — without this fallback, the user sees an opaque 500 with a
    SQLAlchemy traceback. The body deliberately does NOT include the
    raw SQL or constraint internals; if the operator wants those they
    can read the request_id off the structured logs.
    """
    return JSONResponse(status_code=409, content={"error": {
        "code": "conflict",
        "message": ("This change conflicts with existing data — most often "
                     "a unique field (slug, code, email) is already in use."),
        "request_id": getattr(request.state, "request_id", None),
    }})


# NOTE: There is no @app.exception_handler(Exception) here on purpose.
# See the module-level docstring above and the docstring on
# RequestLoggingMiddleware for why the fallback 500 path lives in
# middleware instead. Adding a handler here would be unreachable code
# given how BaseHTTPMiddleware re-raises exceptions, and would risk
# someone removing the actual fallback in logging_mw.py thinking this
# was sufficient.


@app.on_event("startup")
def startup():
    # Background listener for cross-worker setting invalidation.
    threading.Thread(target=start_invalidation_listener, daemon=True).start()
    # Social-automation scheduler — picks up Campaign rows and fires
    # them on their cron schedules. Skipped in test env to keep unit
    # tests from spinning up an APScheduler event loop they don't need.
    if settings.APP_ENV != "test":
        try:
            from app.services.social.scheduler import start as _start_social
            _sched = _start_social()
        except Exception as _e:
            import logging as _log
            _log.getLogger(__name__).warning(
                "social scheduler failed to start: %s", _e,
            )
            _sched = None
        # Visitor Insights nightly rollup — shares the same APScheduler
        # instance so we don't run two event loops. Registration is
        # idempotent; the job itself no-ops when tracking.rollup_enabled
        # is false (which is the default until ops flips it on).
        if _sched is not None:
            try:
                from app.services.tracking.rollup import register as _register_rollup
                _register_rollup(_sched)
            except Exception as _e:
                import logging as _log
                _log.getLogger(__name__).warning(
                    "visitor-insights rollup failed to register: %s", _e,
                )


@app.on_event("shutdown")
def shutdown():
    """Clean shutdown of background services on uvicorn stop."""
    if settings.APP_ENV != "test":
        try:
            from app.services.social.scheduler import stop as _stop_social
            _stop_social()
        except Exception:
            pass


app.include_router(api_router, prefix="/api/v1")


# Static files for admin uploads (images, videos, attached PDFs etc.).
#
# UPLOAD_ROOT env var lets the VPS deploy point at a docker volume
# (cpmai-uploads → /app/uploads inside the container). Locally the
# path defaults to /app/uploads which is bind-mounted from the host's
# backend/uploads/ directory.
#
# IMPORTANT: this runs at module IMPORT time, not just FastAPI startup.
# In CI (GitHub Actions runner) and on contributor machines without a
# /app dir, the default mkdir would crash with PermissionError before
# any test could run — pytest imports main.py purely to register routes.
#
# Policy by environment (no deploy-bypassing fallback):
#   • APP_ENV=test  → tolerate filesystem failures here, log a warning
#                     and skip the /uploads mount. Tests that exercise
#                     uploads run in docker against a real /app/uploads.
#   • anywhere else → RE-RAISE. Production must not start with uploads
#                     silently disabled, because the admin UI assumes
#                     /uploads/* is reachable. A re-raise crashes the
#                     uvicorn boot, which fails deploy.sh's health
#                     probe within 60s and trips the auto-rollback.
import os as _os
import logging as _logging
import mimetypes as _mimetypes
from pathlib import Path as _Path
from fastapi import Request as _Request
from fastapi.responses import (
    FileResponse as _FileResponse, Response as _Response,
    StreamingResponse as _StreamingResponse,
)
from app.core.media_tokens import is_public_image, verify_media_token
_UPLOAD_ROOT = _Path(_os.environ.get("UPLOAD_ROOT", "/app/uploads"))
try:
    _UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
except (OSError, PermissionError) as _e:
    if settings.APP_ENV == "test":
        # CI runner / contributor sandbox: no /app, no write access at
        # /. The application-level surface that depends on this dir is
        # exercised by docker-based integration tests, not the in-process
        # pytest run that imports main here.
        _logging.getLogger(__name__).warning(
            "uploads dir init skipped (APP_ENV=test): could not initialize "
            "%s (%s)", _UPLOAD_ROOT, _e,
        )
    else:
        # Loud failure in dev / staging / production. The deploy script
        # waits on /health for 60s and bails on timeout — that path
        # then triggers auto-rollback via the `on_failure` trap.
        _logging.getLogger(__name__).error(
            "uploads dir init failed at %s — refusing to start with the "
            "feature half-broken; check the cpmai-uploads volume mount + "
            "/app/uploads ownership (Dockerfile pre-creates it as app:app)",
            _UPLOAD_ROOT,
        )
        raise

# Resolved once at import — used to confine every served path inside the
# upload root (defence-in-depth against path traversal).
try:
    _UPLOAD_ROOT_RESOLVED = _UPLOAD_ROOT.resolve()
except OSError:
    _UPLOAD_ROOT_RESOLVED = _UPLOAD_ROOT


@app.get("/uploads/{file_path:path}")
def serve_upload(file_path: str, request: _Request):
    """Serve uploaded media with a hard wall around paid content.

    Replaces the old public ``StaticFiles`` mount. Policy:

      * Images (CMS marketing, course/lesson thumbnails) → public, as
        before.
      * Everything else (lesson videos, attached PDFs/docs, Zoom
        recordings) → requires a valid, path-bound, expiring token minted
        by ``app.core.media_tokens.protected_media_url``. A raw URL copied
        out of devtools therefore can't be shared with non-payers and
        stops working once the token expires.

    Misses (missing file, traversal, missing/invalid/wrong-path token)
    all return an opaque 404 so a probe can't distinguish "file exists
    but you're not allowed" from "no such file".

    Range requests are honoured by Starlette's ``FileResponse`` (HTTP
    206), so in-browser video seeking works.
    """
    # Confine to UPLOAD_ROOT — reject anything that resolves outside it.
    candidate = (_UPLOAD_ROOT / file_path).resolve()
    try:
        candidate.relative_to(_UPLOAD_ROOT_RESOLVED)
    except ValueError:
        return _Response(status_code=404)
    if not candidate.is_file():
        return _Response(status_code=404)

    if not is_public_image(file_path):
        claims = verify_media_token(request.query_params.get("token", ""))
        # Token must be valid AND bound to exactly this path: a token for
        # video A can't be replayed to fetch PDF B.
        if claims is None or claims.get("path") != file_path:
            return _Response(status_code=404)

    return _serve_file_with_range(candidate, request)


def _serve_file_with_range(path: _Path, request: _Request):
    """Serve ``path`` honouring HTTP ``Range`` so the browser can seek
    inside a video.

    Starlette's ``FileResponse`` (this version) doesn't emit 206 /
    ``Accept-Ranges`` on its own, so we parse ``Range`` ourselves: a
    valid range streams a 206 byte-slice; otherwise we serve the whole
    file but still advertise ``Accept-Ranges: bytes`` so the player
    knows seeking is supported.
    """
    file_size = path.stat().st_size
    content_type = (_mimetypes.guess_type(str(path))[0]
                    or "application/octet-stream")
    range_header = request.headers.get("range")

    if range_header and range_header.startswith("bytes="):
        spec = range_header[len("bytes="):].split(",", 1)[0].strip()
        start_s, _, end_s = spec.partition("-")
        try:
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else file_size - 1
        except ValueError:
            return _Response(status_code=416,
                             headers={"Content-Range": f"bytes */{file_size}"})
        end = min(end, file_size - 1)
        if start > end or start >= file_size:
            return _Response(status_code=416,
                             headers={"Content-Range": f"bytes */{file_size}"})
        length = end - start + 1

        def _iter():
            with path.open("rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return _StreamingResponse(
            _iter(), status_code=206, media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )

    return _FileResponse(path, media_type=content_type,
                         headers={"Accept-Ranges": "bytes"})


@app.get("/health")
def health():
    """Liveness + a thin slice of operational state.

    The ``geoip`` block exists so ops monitoring (curl /health from a
    cron) can alert when the mmdb is missing or stale without a
    dedicated probe. We intentionally surface only "are we OK" signal —
    not the full StatusReport — to keep this endpoint cheap and stable.

    GeoIP errors don't fail the overall health response (fail-open): a
    missing mmdb is a degraded state, not an unhealthy one. The page
    still works without GeoIP — leads just won't have country/city set.
    """
    geoip_block = {"database_present": False, "stale": False}
    try:
        # Lazy import so a missing maxminddb dep doesn't break /health.
        from app.services.geoip import get_status
        report = get_status()
        geoip_block = {
            "database_present": report.database_present,
            "database_age_days": report.database_age_days,
            "stale": report.database_stale,
        }
    except Exception:
        # /health must never 500. If geoip is unimportable for any
        # reason, fall back to the default block above.
        pass
    return {
        "status": "ok",
        "version": app.version,
        "geoip": geoip_block,
    }
