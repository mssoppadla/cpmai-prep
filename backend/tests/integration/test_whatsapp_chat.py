"""WhatsApp chat bubble — public /content/site surface + settings."""
import pytest

from tests.conftest import auth_header
from app.core import settings_store as ss_module


@pytest.fixture(autouse=True)
def _fresh_settings():
    ss_module._local.clear()
    try:
        from app.core.redis import redis_client
        for k in redis_client.keys(ss_module.CACHE_PREFIX + "*"):
            redis_client.delete(k)
    except Exception:
        pass
    yield
    ss_module._local.clear()


def _set(client, admin, key, value):
    r = client.patch(f"/api/v1/admin/settings/{key}",
                     headers=auth_header(client, admin.email),
                     json={"value": value})
    assert r.status_code == 200, (key, r.text)


def test_site_hides_whatsapp_by_default(client):
    r = client.get("/api/v1/content/site")
    assert r.status_code == 200
    body = r.json()
    assert body["whatsapp_number"] == ""      # disabled → bubble hidden


def test_site_exposes_sanitized_number_when_enabled(client, admin):
    _set(client, admin, "chat.whatsapp_enabled", True)
    _set(client, admin, "chat.whatsapp_number", "+91 98765-43210")
    _set(client, admin, "chat.whatsapp_prefill", "Hi from the mock!")
    body = client.get("/api/v1/content/site").json()
    assert body["whatsapp_number"] == "919876543210"   # digits only
    assert body["whatsapp_prefill"] == "Hi from the mock!"
    # No auth required — anonymous visitors get it (public endpoint).


def test_site_hides_when_enabled_but_no_number(client, admin):
    _set(client, admin, "chat.whatsapp_enabled", True)
    _set(client, admin, "chat.whatsapp_number", "")
    assert client.get("/api/v1/content/site").json()["whatsapp_number"] == ""


def test_number_validator_rejects_garbage(client, admin):
    h = auth_header(client, admin.email)
    for bad in ("abc", "12345", "+91 abc 99999", "1" * 21):
        r = client.patch("/api/v1/admin/settings/chat.whatsapp_number",
                         headers=h, json={"value": bad})
        assert r.status_code == 422, bad
    # Empty is valid (hides the bubble).
    r = client.patch("/api/v1/admin/settings/chat.whatsapp_number",
                     headers=h, json={"value": ""})
    assert r.status_code == 200
