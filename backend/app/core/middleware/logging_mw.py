"""Structured request/response logger."""
import time
import structlog
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger("http")

SENSITIVE_PATHS = {
    "/api/v1/auth/login", "/api/v1/auth/signup", "/api/v1/auth/password",
    "/api/v1/auth/refresh", "/api/v1/auth/google",
    "/api/v1/payments/verify",
}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        t0 = time.perf_counter()
        path = request.url.path
        try:
            resp = await call_next(request)
        except Exception as e:
            log.exception("http.error", method=request.method, path=path, error=str(e))
            raise
        dur_ms = round((time.perf_counter() - t0) * 1000, 2)
        log.info(
            "http.request",
            method=request.method, path=path, status=resp.status_code,
            duration_ms=dur_ms,
            client_ip=request.client.host if request.client else None,
            sensitive=path in SENSITIVE_PATHS,
        )
        return resp
