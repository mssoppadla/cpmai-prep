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
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS or ["*"])
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


app.include_router(api_router, prefix="/api/v1")


# Static files for admin uploads (images, videos, attached PDFs etc.).
# UPLOAD_ROOT env var lets the VPS deploy point at a docker volume
# (/var/cpmai-uploads → /app/uploads inside the container). Locally
# the path defaults to /app/uploads which is bind-mounted from the
# host's backend/uploads/ directory.
import os as _os
from pathlib import Path as _Path
from fastapi.staticfiles import StaticFiles as _StaticFiles
_UPLOAD_ROOT = _Path(_os.environ.get("UPLOAD_ROOT", "/app/uploads"))
_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
# ``name="uploads"`` lets us reverse the URL via app.url_path_for; the
# admin upload endpoint returns paths relative to this mount.
app.mount("/uploads", _StaticFiles(directory=str(_UPLOAD_ROOT)), name="uploads")


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
