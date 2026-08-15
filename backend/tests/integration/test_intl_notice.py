"""International-payments notice — GET /pricing/intl-notice.

Admin-driven banner for non-India visitors on /pricing while
international checkout is unavailable (Razorpay corporate KYC window,
2026-08). Contract:
  - disabled (default) → never shown, even with force=1
  - enabled + text, force=1 → shown (admin preview from India)
  - enabled, no positive non-IN GeoIP match → hidden (test client IPs
    don't geolocate; unknown must hide, not nag)
  - both settings editable through the admin settings API (they're in
    the EDITABLE allowlist — that registration is part of the feature)
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


def test_admin_can_enable_and_preview_with_force(client, admin):
    _set(client, admin, "pricing.intl_notice_enabled", True)
    _set(client, admin, "pricing.intl_notice_text",
         "Intl payments back soon — email us.")
    r = client.get(URL + "?force=1").json()
    assert r == {"show": True, "message": "Intl payments back soon — email us."}


def test_enabled_but_unknown_geoip_stays_hidden(client, admin):
    """Test-client IPs never geolocate → unknown country must HIDE the
    banner (only a positive non-IN match shows it)."""
    _set(client, admin, "pricing.intl_notice_enabled", True)
    _set(client, admin, "pricing.intl_notice_text", "hello world")
    assert client.get(URL).json() == {"show": False, "message": ""}


def test_disable_wins_over_force(client, admin):
    _set(client, admin, "pricing.intl_notice_enabled", True)
    _set(client, admin, "pricing.intl_notice_text", "x" * 20)
    _set(client, admin, "pricing.intl_notice_enabled", False)
    assert client.get(URL + "?force=1").json() == {"show": False, "message": ""}


def test_blank_text_hides_even_when_enabled(client, admin):
    _set(client, admin, "pricing.intl_notice_enabled", True)
    _set(client, admin, "pricing.intl_notice_text", "   ")
    assert client.get(URL + "?force=1").json() == {"show": False, "message": ""}
