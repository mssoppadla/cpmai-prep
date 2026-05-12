"""Unhandled-exception 500 responses MUST carry CORS headers.

Regression for the bug where the chat callback form showed
"TypeError: Failed to fetch" on prod. Root cause: an
``InvalidTextRepresentation`` raised by SQLAlchemy (Postgres enum
missing a value) fell through every specific exception handler and hit
Starlette's built-in ``ServerErrorMiddleware``, which runs OUTSIDE the
CORS middleware stack. The 500 response had no
``Access-Control-Allow-Origin`` header, so the browser refused to
expose the response body to JS — surfacing as an opaque
``TypeError: Failed to fetch`` instead of a useful 500.

The fallback ``@app.exception_handler(Exception)`` in ``main.py``
routes those errors through FastAPI's middleware stack so CORS
attaches the right headers and the contract-shaped error body
(``{"error": {"code": "internal_error", ...}}``) reaches the client.

These tests pin the contract so the regression can't return.
"""
from fastapi import APIRouter
from fastapi.testclient import TestClient

# We deliberately register an endpoint that ALWAYS crashes with an
# unhandled exception, so we can assert the 500 path. We do this on
# the live ``app`` (imported by tests) inside the test module so it
# only exists for this test suite.
_test_router = APIRouter()


@_test_router.get("/__crash__")
def _always_crashes():
    raise RuntimeError("deliberate crash for the 500-handler test")


def _install_crash_route(app):
    # Idempotent — multiple test runs in the same session shouldn't
    # double-register the route.
    if any(getattr(r, "path", None) == "/api/v1/__crash__" for r in app.routes):
        return
    app.include_router(_test_router, prefix="/api/v1")


def _client_for_500_tests():
    """A TestClient that DOESN'T re-raise server exceptions. The default
    ``TestClient(app)`` has ``raise_server_exceptions=True``, which short-
    circuits Starlette before our fallback handler can run — so we'd see
    the bare exception in the test even though prod sees the 500. Set the
    flag to False so the handler chain matches prod behavior."""
    from app.main import app
    _install_crash_route(app)
    return TestClient(app, raise_server_exceptions=False)


# Use an Origin that's in the test config's CORS_ORIGINS allow list
# (backend/.env: ["http://localhost:3000"]). With a non-allowed origin
# the middleware would correctly omit Access-Control-Allow-Origin —
# which is the right prod behavior, but it would mask the bug we're
# testing for (whether the 500 response goes through CORS middleware
# AT ALL).
_ALLOWED_ORIGIN = "http://localhost:3000"


def test_unhandled_500_returns_cors_headers_and_contract_body(client):
    # The shared ``client`` fixture has dependency_overrides set up for the
    # test DB. We don't need those here (the crash route doesn't touch
    # the DB), but we keep the param so pytest builds the same app.
    test_client = _client_for_500_tests()

    r = test_client.get(
        "/api/v1/__crash__",
        headers={"Origin": _ALLOWED_ORIGIN},
    )

    # 500 status — the handler turns the unhandled exception into a clean 500.
    assert r.status_code == 500, r.text

    # The whole point of the fix: CORS headers MUST be present so the
    # browser can expose the response to JS. Before the fallback handler,
    # this header was absent because the response bypassed the CORS
    # middleware (Starlette's ServerErrorMiddleware sits OUTSIDE it).
    headers_lower = {k.lower(): v for k, v in r.headers.items()}
    assert headers_lower.get("access-control-allow-origin") == _ALLOWED_ORIGIN, (
        f"CORS Allow-Origin missing or mismatched on 500 — headers: {dict(r.headers)}"
    )

    # Contract-shaped body so the frontend's ApiError parses it
    body = r.json()
    assert body == {"error": {
        "code": "internal_error",
        "message": "Something went wrong on our end. We've logged it.",
        # request_id may be None in tests; key MUST exist
        "request_id": body["error"]["request_id"],
    }}


def test_unhandled_500_body_never_leaks_traceback(client):
    """Defense in depth: the response body must not include any of the
    real exception text. The traceback goes to structured logs only."""
    test_client = _client_for_500_tests()

    r = test_client.get(
        "/api/v1/__crash__",
        headers={"Origin": _ALLOWED_ORIGIN},
    )
    body_text = r.text.lower()
    assert "deliberate crash" not in body_text
    assert "runtimeerror" not in body_text
    assert "traceback" not in body_text
