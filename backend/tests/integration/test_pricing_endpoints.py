"""Public pricing endpoints — list active plans + quote with offer code."""
from app.models.plan import Plan
from app.models.offer import OfferCode


def _seed_plan(db, *, slug="exam-bundle", base=99900, discount=None,
                is_active=True) -> Plan:
    p = Plan(name=f"Plan {slug}", slug=slug, bundle_type="exam_bundle",
             base_price_paise=base, discount_price_paise=discount,
             currency="INR", duration_days=365, perks={},
             is_active=is_active, display_order=10)
    db.add(p); db.commit(); db.refresh(p)
    return p


def _seed_offer(db, **kw) -> OfferCode:
    o = OfferCode(code=kw.pop("code").upper(),
                   discount_type=kw.pop("discount_type", "percent"),
                   discount_value=kw.pop("discount_value", 10),
                   is_active=kw.pop("is_active", True), **kw)
    db.add(o); db.commit(); db.refresh(o)
    return o


# ============================================================ list plans
def test_list_active_plans_excludes_inactive(client, db):
    _seed_plan(db, slug="active-1", base=10000)
    _seed_plan(db, slug="hidden", base=10000, is_active=False)
    r = client.get("/api/v1/pricing/plans")
    assert r.status_code == 200
    slugs = [p["slug"] for p in r.json()]
    assert "active-1" in slugs
    assert "hidden" not in slugs


# =============================================================== quote
def test_quote_returns_full_breakdown(client, db):
    _seed_plan(db, base=100000)
    r = client.post("/api/v1/pricing/quote", json={
        "plan_slug": "exam-bundle"})
    assert r.status_code == 200
    body = r.json()
    assert body["final_price_paise"] == 100000
    assert body["offer_applied"] is False


def test_quote_applies_valid_offer(client, db):
    _seed_plan(db, base=100000)
    _seed_offer(db, code="SAVE10", discount_type="percent",
                discount_value=10)
    r = client.post("/api/v1/pricing/quote", json={
        "plan_slug": "exam-bundle", "offer_code": "save10"})
    body = r.json()
    assert body["offer_applied"] is True
    assert body["final_price_paise"] == 90000


def test_quote_unknown_plan_404(client, db):
    r = client.post("/api/v1/pricing/quote", json={
        "plan_slug": "nope"})
    assert r.status_code == 404


def test_quote_invalid_offer_is_soft_fail(client, db):
    _seed_plan(db, base=100000)
    r = client.post("/api/v1/pricing/quote", json={
        "plan_slug": "exam-bundle", "offer_code": "GHOST"})
    assert r.status_code == 200
    body = r.json()
    assert body["offer_applied"] is False
    assert body["offer_reason"]
    assert body["final_price_paise"] == 100000
