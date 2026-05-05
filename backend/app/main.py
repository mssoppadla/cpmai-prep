"""FastAPI entrypoint with full middleware stack and exception handling."""
import threading
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.exceptions import RequestValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.exceptions import AppError
from app.core.settings_store import start_invalidation_listener
from app.core.middleware.correlation import CorrelationMiddleware
from app.core.middleware.security_headers import SecurityHeadersMiddleware
from app.core.middleware.logging_mw import RequestLoggingMiddleware
from app.api.v1.router import api_router

configure_logging()

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)

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
                   "X-Request-ID", "X-Session-ID", "X-Anon-ID",
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


@app.on_event("startup")
def startup():
    # Background listener for cross-worker setting invalidation.
    threading.Thread(target=start_invalidation_listener, daemon=True).start()


app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}
