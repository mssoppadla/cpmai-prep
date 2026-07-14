"""Backend pieces of the SEO/ads rollout.

Pins:
  * /payments/orders stamps utm_source/medium/campaign onto the
    Payment row (revenue-per-campaign attribution), tolerates absence
  * /content/live-sessions is public, upcoming-only, and never leaks
    join/start URLs
  * /content/site exposes the ads config block with safe defaults
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.payment import Payment
from app.models.zoom import ZoomSession
from tests.conftest import auth_header

# Reuse the payment-flow fixtures (FakeProvider + plan seeder).
from tests.integration.test_payment_flow import fake_provider, _seed_plan  # noqa: F401


def test_order_stores_utm_attribution(client, db, user, fake_provider):  # noqa: F811
    _seed_plan(db, slug="utm-bundle", name="UTM Bundle")
    r = client.post("/api/v1/payments/orders",
                    headers=auth_header(client, user.email),
                    json={"plan_slug": "utm-bundle",
                          "utm_source": "google",
                          "utm_medium": "cpc",
                          "utm_campaign": "july-launch"})
    assert r.status_code == 201, r.text
    payment = (db.query(Payment)
               .filter_by(provider_order_id=r.json()["order_id"]).first())
    assert payment.utm_source == "google"
    assert payment.utm_medium == "cpc"
    assert payment.utm_campaign == "july-launch"


def test_order_without_utm_stays_null(client, db, user, fake_provider):  # noqa: F811
    _seed_plan(db, slug="no-utm-bundle", name="No UTM Bundle")
    r = client.post("/api/v1/payments/orders",
                    headers=auth_header(client, user.email),
                    json={"plan_slug": "no-utm-bundle"})
    assert r.status_code == 201, r.text
    payment = (db.query(Payment)
               .filter_by(provider_order_id=r.json()["order_id"]).first())
    assert payment.utm_source is None
    assert payment.utm_campaign is None


def test_live_sessions_public_upcoming_only_no_join_urls(client, db):
    now = datetime.now(timezone.utc)

    def seed(title, *, offset_h, status="scheduled"):
        s = ZoomSession(title=title, status=status,
                        scheduled_at=now + timedelta(hours=offset_h),
                        zoom_join_url="https://zoom.us/j/secret-join",
                        zoom_start_url="https://zoom.us/s/secret-start")
        db.add(s)
    seed("Upcoming class", offset_h=48)
    seed("Draft class", offset_h=48, status="draft")
    seed("Cancelled class", offset_h=48, status="cancelled")
    seed("Old class", offset_h=-100)
    db.commit()

    r = client.get("/api/v1/content/live-sessions")   # anonymous
    assert r.status_code == 200
    titles = [s["title"] for s in r.json()]
    assert "Upcoming class" in titles
    assert "Draft class" not in titles
    assert "Cancelled class" not in titles
    assert "Old class" not in titles
    assert "secret" not in r.text          # join URLs never serialised


def test_site_chrome_exposes_ads_defaults(client):
    r = client.get("/api/v1/content/site")
    assert r.status_code == 200
    ads = r.json()["ads"]
    assert ads["enabled"] is False          # safe default: no tags
    assert ads["google_tag_id"] == ""
    assert ads["linkedin_partner_id"] == ""
