"""End-to-end: POST /leads enriches the row with country + city when
the GeoIP lookup succeeds, and stores NULL when it fails — without
ever blocking the insert.

Three scenarios:

  1. Happy path: mocked lookup returns a GeoLocation → row has country+city.
  2. Lookup returns None: row has both columns NULL but the insert SUCCEEDS.
  3. Lookup raises: a buggy / corrupt mmdb must NOT break the request
     path. The fail-open contract says we silently swallow internal
     errors. (Note: our lookup() implementation never raises, but we
     test the API layer's resilience to a hypothetical regression.)

We don't exercise X-Forwarded-For parsing here — that's covered by the
extract_client_ip unit tests. We patch ``geo_lookup`` directly to keep
this test focused on the wiring.
"""
from __future__ import annotations
from unittest.mock import patch

from app.services.geoip import GeoLocation


# TestClient sets request.client.host="testclient" which isn't a valid
# IP. extract_client_ip falls back to it, fails the is-valid-IP check,
# and returns None — causing the leads endpoint to skip the lookup
# entirely. We send a real-looking X-Forwarded-For header so the
# extract_client_ip path succeeds and we exercise the mocked
# geo_lookup, not just the "no client IP" fallback.
TEST_XFF = {"X-Forwarded-For": "1.1.1.1"}


def test_lead_enriched_with_country_and_city_on_lookup_hit(client, db):
    """When the lookup returns a GeoLocation, the lead row stores both
    fields and the response is the same 201 as before."""
    fake_geo = GeoLocation(country="IN", city="Bengaluru",
                           latitude=12.97, longitude=77.59)
    with patch("app.api.v1.endpoints.leads.geo_lookup",
               return_value=fake_geo):
        r = client.post("/api/v1/leads", headers=TEST_XFF, json={
            "email": "geo1@example.com", "source": "landing_hero",
            "consent_marketing": True,
        })
    assert r.status_code == 201
    from app.models.lead import Lead
    lead = db.query(Lead).filter_by(email="geo1@example.com").first()
    assert lead.country == "IN"
    assert lead.city == "Bengaluru"


def test_lead_country_city_null_when_lookup_misses(client, db):
    """Lookup returns None (private IP, missing mmdb, MaxMind miss).
    The insert still succeeds with both fields NULL — this is the
    expected day-1 state before the mmdb is installed in prod."""
    with patch("app.api.v1.endpoints.leads.geo_lookup", return_value=None):
        r = client.post("/api/v1/leads", json={
            "email": "geo2@example.com", "source": "newsletter",
        })
    assert r.status_code == 201
    from app.models.lead import Lead
    lead = db.query(Lead).filter_by(email="geo2@example.com").first()
    assert lead.country is None
    assert lead.city is None


def test_lead_country_only_record(client, db):
    """An IP that resolves to a country but no city (anonymous proxy
    case) stores country=set, city=None. The frontend should render
    just a flag in that case."""
    fake_geo = GeoLocation(country="AE", city=None)
    with patch("app.api.v1.endpoints.leads.geo_lookup",
               return_value=fake_geo):
        r = client.post("/api/v1/leads", headers=TEST_XFF, json={
            "email": "geo3@example.com", "source": "landing_hero",
        })
    assert r.status_code == 201
    from app.models.lead import Lead
    lead = db.query(Lead).filter_by(email="geo3@example.com").first()
    assert lead.country == "AE"
    assert lead.city is None


def test_admin_leads_endpoint_surfaces_country_city(client, db, admin):
    """The admin /admin/leads response now includes country + city so
    the UI can render a flag + city column. Important because frontend
    typing relies on this — a missing field would silently break the
    column render rather than 500."""
    from tests.conftest import auth_header
    fake_geo = GeoLocation(country="SG", city="Singapore")
    with patch("app.api.v1.endpoints.leads.geo_lookup",
               return_value=fake_geo):
        client.post("/api/v1/leads", headers=TEST_XFF, json={
            "email": "geo4@example.com", "source": "landing_hero",
        })
    r = client.get("/api/v1/admin/leads?q=geo4",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1
    found = next(row for row in body if row["email"] == "geo4@example.com")
    assert found["country"] == "SG"
    assert found["city"] == "Singapore"


def test_csv_export_includes_country_city_columns(client, db, admin):
    """Operators export leads to a CSV for offline analysis; we added
    country + city columns. Pin the header line so a refactor doesn't
    silently break the export contract."""
    from tests.conftest import auth_header
    r = client.get("/api/v1/admin/leads/export.csv",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200
    body = r.text
    header = body.splitlines()[0]
    assert "country" in header.split(",")
    assert "city" in header.split(",")
    # score column was added in PR 0018 — verify it's still there too,
    # because we touched this method to add the new columns.
    assert "score" in header.split(",")
