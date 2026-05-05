"""Daily chat limits (anon = 5, auth = 25 — both runtime-configurable)."""
from tests.conftest import auth_header


def _send(client, **kwargs):
    return client.post("/api/v1/assistant/chat",
                       json={"message": "What is CPMAI?"}, **kwargs)


def test_anonymous_quota_is_lower_than_authenticated(client):
    client.cookies.set("aid", "anon-test-12345")
    r = _send(client)
    assert r.status_code == 200
    assert int(r.headers["X-Chat-Quota-Limit"]) == 5


def test_authenticated_quota_is_25_by_default(client, user):
    headers = auth_header(client, user.email)
    r = _send(client, headers=headers)
    assert r.status_code == 200
    assert int(r.headers["X-Chat-Quota-Limit"]) == 25
    assert int(r.headers["X-Chat-Quota-Used"]) == 1
    assert int(r.headers["X-Chat-Quota-Remaining"]) == 24


def test_anonymous_blocked_after_limit(client):
    client.cookies.set("aid", "anon-block-12345")
    for _ in range(5):
        r = _send(client)
        assert r.status_code == 200
    r = _send(client)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "chat_daily_limit_reached"


def test_quota_changes_take_effect_at_runtime(client, admin):
    """Bumping the limit via /admin/settings should propagate immediately."""
    headers = auth_header(client, admin.email)
    r = client.patch("/api/v1/admin/settings/chat.daily_limit.anonymous",
                     headers=headers, json={"value": 2})
    assert r.status_code == 200
    client.cookies.set("aid", "anon-runtime-12345")
    for _ in range(2):
        assert _send(client).status_code == 200
    assert _send(client).status_code == 429
