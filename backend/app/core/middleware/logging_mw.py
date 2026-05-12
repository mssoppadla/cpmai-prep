"""Structured request/response logger."""
import time
import structlog
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger("http")

SENSITIVE_PATHS = {
    "/api/v1/auth/login", "/api/v1/auth/signup", "/api/v1/auth/password",
    "/api/v1/auth/refresh", "/api/v1/auth/google",
    "/api/v1/payments/verify",
}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request + last-ditch handler for unhandled exceptions.

    Why this middleware owns the fallback 500 path (and not
    ``@app.exception_handler(Exception)``):

    Starlette's ``BaseHTTPMiddleware`` (which we inherit) wraps the inner
    ASGI app in a task group. When the route or an inner middleware
    raises an unhandled exception, the exception escapes through
    ``call_next`` and lands in OUR try/except below — at this point it
    has ALREADY bypassed FastAPI's ``ExceptionMiddleware`` (where
    ``@app.exception_handler(Exception)`` lives), because the task-group
    re-raise crosses the boundary.

    If we ``raise`` here, the exception propagates to Starlette's
    top-level ``ServerErrorMiddleware``, which sits OUTSIDE the
    ``CORSMiddleware`` in the stack. That middleware generates a bare
    500 with no CORS headers, and the browser surfaces it as
    ``TypeError: Failed to fetch`` — completely masking the real error
    from anyone debugging via devtools.

    Solution: catch here, log here, and RETURN a contract-shaped 500
    response instead of re-raising. The response then propagates back
    out through the rest of the middleware stack — including
    ``CORSMiddleware`` — so the browser sees a proper JSON 500 with
    ``Access-Control-Allow-Origin`` set.

    Body shape mirrors the contract ``{"error": {"code", "message",
    "request_id"}}`` so the frontend's ``ApiError`` parses it like every
    other error. The exception traceback goes to structured logs only;
    it is never echoed to the client.
    """

    async def dispatch(self, request, call_next):
        t0 = time.perf_counter()
        path = request.url.path
        try:
            resp = await call_next(request)
        except Exception as e:
            log.exception(
                "http.unhandled_error",
                method=request.method, path=path, error=str(e),
                exc_type=type(e).__name__,
            )
            request_id = getattr(request.state, "request_id", None)
            resp = JSONResponse(status_code=500, content={"error": {
                "code": "internal_error",
                "message": "Something went wrong on our end. We've logged it.",
                "request_id": request_id,
            }})
        dur_ms = round((time.perf_counter() - t0) * 1000, 2)
        log.info(
            "http.request",
            method=request.method, path=path, status=resp.status_code,
            duration_ms=dur_ms,
            client_ip=request.client.host if request.client else None,
            sensitive=path in SENSITIVE_PATHS,
        )
        return resp
