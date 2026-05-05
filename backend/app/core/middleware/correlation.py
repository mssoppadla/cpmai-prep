"""Adds request_id, session_id, anon_id to each request and binds them to logs."""
import uuid
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from asgi_correlation_id.context import correlation_id


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        sid = request.headers.get("X-Session-ID") or request.cookies.get("sid")
        aid = request.headers.get("X-Anon-ID") or request.cookies.get("aid")

        correlation_id.set(rid)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=rid, session_id=sid, anon_id=aid,
        )
        request.state.request_id = rid
        request.state.session_id = sid
        request.state.anon_id = aid

        resp = await call_next(request)
        resp.headers["X-Request-ID"] = rid
        return resp
