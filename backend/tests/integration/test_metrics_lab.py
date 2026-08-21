"""Classification Metrics Lab — public teaching-copy endpoint + admin settings."""
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


def test_lab_config_is_public_with_empty_defaults(client):
    r = client.get("/api/v1/content/labs/metrics-lab")
    assert r.status_code == 200
    body = r.json()
    # Empty strings signal "use the frontend's built-in default" — the
    # page can never be blanked by a wiped setting.
    assert set(body.keys()) == {"title", "takeaway_html", "reference_html"}
    assert body["title"]   # always a display name, even unseeded


def test_admin_edits_flow_to_public_endpoint(client, admin):
    h = auth_header(client, admin.email)
    r = client.patch(
        "/api/v1/admin/settings/labs.metrics_lab_takeaway_html",
        headers=h,
        json={"value": "<b>Custom move 1</b> — my own wording.<br>More."})
    assert r.status_code == 200, r.text
    r = client.patch(
        "/api/v1/admin/settings/labs.metrics_lab_reference_html",
        headers=h,
        json={"value": "<table><tr><td><span style=\"color:#b91c1c\">"
                       "New row</span></td></tr></table>"})
    assert r.status_code == 200, r.text
    body = client.get("/api/v1/content/labs/metrics-lab").json()
    assert "Custom move 1" in body["takeaway_html"]
    assert "New row" in body["reference_html"]
    # Admin-driven display name
    r = client.patch("/api/v1/admin/settings/labs.metrics_lab_title",
                     headers=h, json={"value": "Metrics Playground"})
    assert r.status_code == 200, r.text
    body = client.get("/api/v1/content/labs/metrics-lab").json()
    assert body["title"] == "Metrics Playground"
    # No auth was needed to read — SEO crawlers see the copy.
