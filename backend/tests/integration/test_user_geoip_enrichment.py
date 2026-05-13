"""End-to-end: signup + login set User.country/city + last_login_*.

What we test:

  1. POST /auth/signup with a mocked geo_lookup populates user.country
     + user.city AND user.last_login_ip + user.last_login_country.
  2. POST /auth/login on an existing user updates last_login_* but
     does NOT overwrite the original country/city (snapshot semantics).
  3. If the lookup misses, signup still succeeds — fail-open contract.

We don't mock at extract_client_ip — TestClient's request.client.host
is "testclient" which extract_client_ip correctly rejects, so we send
a real-looking X-Forwarded-For header. Same pattern as the lead test.
"""
from __future__ import annotations
from unittest.mock import patch

from app.services.geoip import GeoLocation


TEST_XFF = {"X-Forwarded-For": "1.1.1.1"}


def test_signup_sets_country_city_and_last_login_country(client, db):
    """The signup endpoint must populate BOTH the snapshot fields
    (country/city) AND the last-login fields. Treats signup as the
    first login session."""
    fake = GeoLocation(country="IN", city="Bengaluru")
    with patch("app.api.v1.endpoints.auth.geo_lookup", return_value=fake):
        r = client.post("/api/v1/auth/signup", headers=TEST_XFF, json={
            "email": "geo-signup@example.com",
            "password": "asecurepassword123",
            "name": "GeoUser",
        })
    assert r.status_code == 201, r.text

    from app.models.user import User
    user = db.query(User).filter_by(email="geo-signup@example.com").first()
    assert user.country == "IN"
    assert user.city == "Bengaluru"
    assert user.last_login_country == "IN"
    assert user.last_login_ip == "1.1.1.1"


def test_signup_succeeds_when_lookup_misses(client, db):
    """If the geoip lookup returns None (private IP, no mmdb, MaxMind
    miss), the signup must still succeed. country/city stay NULL."""
    with patch("app.api.v1.endpoints.auth.geo_lookup", return_value=None):
        r = client.post("/api/v1/auth/signup", headers=TEST_XFF, json={
            "email": "geo-nogeo@example.com",
            "password": "asecurepassword123",
            "name": "NoGeo",
        })
    assert r.status_code == 201
    from app.models.user import User
    user = db.query(User).filter_by(email="geo-nogeo@example.com").first()
    assert user.country is None
    assert user.city is None
    # last_login_ip should still be set even though geo lookup missed.
    assert user.last_login_ip == "1.1.1.1"
    assert user.last_login_country is None


def test_login_updates_last_login_country_but_preserves_signup_country(client, db):
    """Snapshot semantics: country/city are SIGNUP-time. last_login_*
    refreshes on each login. A user who signs up in IN and later logs
    in from SG should have:
        country = "IN"
        last_login_country = "SG"
    """
    # Step 1: sign up from IN.
    with patch("app.api.v1.endpoints.auth.geo_lookup",
               return_value=GeoLocation(country="IN", city="Bengaluru")):
        r = client.post("/api/v1/auth/signup",
            headers={"X-Forwarded-For": "1.1.1.1"}, json={
                "email": "mover@example.com",
                "password": "asecurepassword123",
                "name": "Mover",
            })
    assert r.status_code == 201

    # Step 2: log in from SG (different IP, different country in mock).
    with patch("app.api.v1.endpoints.auth.geo_lookup",
               return_value=GeoLocation(country="SG", city="Singapore")):
        r = client.post("/api/v1/auth/login",
            headers={"X-Forwarded-For": "2606:4700::1"}, json={
                "email": "mover@example.com",
                "password": "asecurepassword123",
            })
    assert r.status_code == 200, r.text

    from app.models.user import User
    user = db.query(User).filter_by(email="mover@example.com").first()
    # Snapshot preserved.
    assert user.country == "IN"
    assert user.city == "Bengaluru"
    # Last-login refreshed.
    assert user.last_login_country == "SG"
    assert user.last_login_ip == "2606:4700::1"


def test_admin_users_endpoint_surfaces_geo_fields(client, db, admin):
    """The admin /users response must include country/city/last_login_*
    so the UI's Location column + Last-login tooltip can render."""
    from tests.conftest import auth_header
    # Make sure a user exists with geo fields populated.
    with patch("app.api.v1.endpoints.auth.geo_lookup",
               return_value=GeoLocation(country="AE", city="Dubai")):
        client.post("/api/v1/auth/signup",
            headers={"X-Forwarded-For": "1.1.1.1"}, json={
                "email": "ae-user@example.com",
                "password": "asecurepassword123",
                "name": "AEUser",
            })

    r = client.get("/api/v1/admin/users",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200
    body = r.json()
    found = next(u for u in body if u["email"] == "ae-user@example.com")
    assert found["country"] == "AE"
    assert found["city"] == "Dubai"
    assert found["last_login_country"] == "AE"
    assert found["last_login_ip"] == "1.1.1.1"


def test_admin_contacts_feed_surfaces_user_location(client, db, admin):
    """The unified Contacts feed at /admin/leads/contacts must surface
    country + city for USER rows, not just lead rows.

    Why this exists: the original Contacts endpoint built ContactRow
    for users WITHOUT setting country/city, even though those fields
    are populated on the User model at signup time. The Contacts page
    rendered "—" in the Location column for every user. Pin both the
    backend mapping and the UI contract here so a future refactor
    doesn't silently strip the location off user rows again.
    """
    from tests.conftest import auth_header
    # Sign up a user with geo fields populated via the auth hook.
    with patch("app.api.v1.endpoints.auth.geo_lookup",
               return_value=GeoLocation(country="SG", city="Singapore")):
        client.post("/api/v1/auth/signup",
            headers={"X-Forwarded-For": "1.1.1.1"}, json={
                "email": "contacts-feed-user@example.com",
                "password": "asecurepassword123",
                "name": "ContactsFeedUser",
            })

    r = client.get(
        "/api/v1/admin/leads/contacts?q=contacts-feed-user",
        headers=auth_header(client, admin.email),
    )
    assert r.status_code == 200
    body = r.json()
    user_row = next(row for row in body
                    if row["kind"] == "user"
                    and row["email"] == "contacts-feed-user@example.com")
    assert user_row["country"] == "SG"
    assert user_row["city"] == "Singapore"


def test_admin_contacts_feed_user_falls_back_to_last_login_country(client, db, admin):
    """If a user pre-dates the signup-time enrichment (their
    user.country is NULL) but has a populated user.last_login_country
    from a more recent login, the Contacts feed should still surface a
    flag rather than rendering "—".

    This is the legacy-user-friendly case: existing users who signed up
    before PR-A have NULL country/city, but their next login will set
    last_login_*. We fall back to that so the admin sees something
    useful immediately rather than waiting for "users created since
    PR-A merge" to be the only enriched rows.
    """
    from tests.conftest import auth_header
    from app.models.user import User
    from app.core.security import hash_password

    # Create a user as if they predated GeoIP — country/city NULL.
    legacy = User(
        email="legacy-user@example.com",
        password_hash=hash_password("asecurepassword123"),
        name="Legacy",
    )
    db.add(legacy); db.commit()

    # Now simulate that they logged in once (PR-A's login hook fires),
    # setting last_login_country/last_login_ip but NOT touching
    # country/city (snapshot semantics — never overwritten).
    with patch("app.api.v1.endpoints.auth.geo_lookup",
               return_value=GeoLocation(country="IN", city="Bengaluru")):
        client.post("/api/v1/auth/login",
            headers={"X-Forwarded-For": "1.1.1.1"}, json={
                "email": "legacy-user@example.com",
                "password": "asecurepassword123",
            })

    db.refresh(legacy)
    assert legacy.country is None              # never overwritten
    assert legacy.last_login_country == "IN"   # updated on login

    r = client.get(
        "/api/v1/admin/leads/contacts?q=legacy-user",
        headers=auth_header(client, admin.email),
    )
    assert r.status_code == 200
    body = r.json()
    user_row = next(row for row in body
                    if row["kind"] == "user"
                    and row["email"] == "legacy-user@example.com")
    # Falls back to last_login_country for country (legacy user has no
    # signup-time snapshot).
    assert user_row["country"] == "IN"
    # city is NOT populated from last_login (we don't store
    # last_login_city). That's fine — the UI renders just the flag
    # when city is missing.
    assert user_row["city"] is None
