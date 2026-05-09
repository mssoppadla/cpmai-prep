"""FastAPI entrypoint with full middleware stack and exception handling."""
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


@app.on_event("startup")
def startup():
    # Background listener for cross-worker setting invalidation.
    threading.Thread(target=start_invalidation_listener, daemon=True).start()


app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}
