"""International-payments notice — GET /pricing/intl-notice.

Admin-driven banner on /pricing while international checkout is
unavailable (Razorpay corporate KYC window, 2026-08). Contract:
  - disabled (default) → never shown, even with force=1
  - enabled + text + audience "all" (the default) → shown to EVERY
    visitor, no GeoIP involved
  - audience "non_in" → only a positive non-India GeoIP match shows it
    (test client IPs don't geolocate; unknown must hide, not nag);
    force=1 previews it from India
  - all three settings editable through the admin settings API
    (EDITABLE allowlist registration is part of the feature)
"""
from tests.conftest import auth_header

URL = "/api/v1/pricing/intl-notice"


def _set(client, admin, key, value):
    r = client.patch(f"/api/v1/admin/settings/{key}",
                     headers=auth_header(client, admin.email),
                     json={"value": value})
    assert r.status_code == 200, r.text


def test_disabled_by_default_even_with_force(client):
    assert client.get(URL).json() == {"show": False, "message": ""}
    assert client.get(URL + "?force=1").json() == {"show": False, "message": ""}


def test_audience_all_shows_to_everyone(client, admin):
    """Default audience "all": enabled + text → every visitor sees it,
    GeoIP not consulted (test-client IPs don't geolocate and it still
    shows — proof the geo path is bypassed)."""
    _set(client, admin, "pricing.intl_notice_enabled", True)
    _set(client, admin, "pricing.intl_notice_text",
         "Intl payments back soon — email us.")
    r = client.get(URL).json()
    assert r == {"show": True, "message": "Intl payments back soon — email us."}


def test_audience_non_in_with_unknown_geoip_stays_hidden(client, admin):
    """Audience "non_in": test-client IPs never geolocate → unknown
    country must HIDE the banner (only a positive non-IN match shows)."""
    _set(client, admin, "pricing.intl_notice_enabled", True)
    _set(client, admin, "pricing.intl_notice_text", "hello world")
    _set(client, admin, "pricing.intl_notice_audience", "non_in")
    assert client.get(URL).json() == {"show": False, "message": ""}


def test_audience_non_in_force_previews_from_india(client, admin):
    _set(client, admin, "pricing.intl_notice_enabled", True)
    _set(client, admin, "pricing.intl_notice_text", "preview me")
    _set(client, admin, "pricing.intl_notice_audience", "non_in")
    assert client.get(URL + "?force=1").json() == {
        "show": True, "message": "preview me"}


def test_audience_rejects_unknown_values(client, admin):
    _set(client, admin, "pricing.intl_notice_enabled", True)
    r = client.patch("/api/v1/admin/settings/pricing.intl_notice_audience",
                     headers=auth_header(client, admin.email),
                     json={"value": "everyone"})
    assert r.status_code == 422


def test_disable_wins_over_force(client, admin):
    _set(client, admin, "pricing.intl_notice_enabled", True)
    _set(client, admin, "pricing.intl_notice_text", "x" * 20)
    _set(client, admin, "pricing.intl_notice_enabled", False)
    assert client.get(URL + "?force=1").json() == {"show": False, "message": ""}


def test_blank_text_hides_even_when_enabled(client, admin):
    _set(client, admin, "pricing.intl_notice_enabled", True)
    _set(client, admin, "pricing.intl_notice_text", "   ")
    assert client.get(URL + "?force=1").json() == {"show": False, "message": ""}
