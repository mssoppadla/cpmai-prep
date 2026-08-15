"""/content/landing — admin-editable copy payload pins.

Currently pins the /pricing subtitle: its default matches the copy the
page shipped with (so a fresh install renders identically), and an
admin edit through Runtime Settings flows straight into the payload.
"""
from tests.conftest import auth_header

URL = "/api/v1/content/landing"


def test_pricing_subtitle_default_matches_shipped_copy(client):
    r = client.get(URL)
    assert r.status_code == 200, r.text
    assert r.json()["pricing_subtitle"] == (
        "One-time payment, 1-year access. All plans include "
        "CPMAI-aligned mock exams and the AI tutor."
    )


def test_pricing_subtitle_is_admin_editable(client, admin):
    r = client.patch("/api/v1/admin/settings/pricing.subtitle",
                     headers=auth_header(client, admin.email),
                     json={"value": "Now with monthly subscriptions!"})
    assert r.status_code == 200, r.text
    assert client.get(URL).json()["pricing_subtitle"] == \
        "Now with monthly subscriptions!"
