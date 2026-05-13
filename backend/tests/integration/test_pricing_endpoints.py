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


def test_quote_returns_gst_breakdown_when_admin_enables_it(client, db, monkeypatch):
    """With pricing.gst_percent=18 set, /pricing/quote returns the
    subtotal/gst/final split end-to-end."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: (
            18 if k == "pricing.gst_percent"
            else False if k == "pricing.stack_offer_with_discount"
            else default))
    _seed_plan(db, base=100_000)
    r = client.post("/api/v1/pricing/quote", json={"plan_slug": "exam-bundle"})
    assert r.status_code == 200
    body = r.json()
    assert body["subtotal_paise"] == 100_000
    assert body["gst_percent"] == 18
    assert body["gst_paise"] == 18_000
    assert body["final_price_paise"] == 118_000


# ============================================================ currencies
# /pricing/currencies + /pricing/quote with currency param.

def test_list_currencies_returns_inr_and_usd_by_default(client, db, monkeypatch):
    """The default seed includes INR + USD + EUR + GBP + SGD + AED.
    The endpoint should return them all with their symbols and a
    has_fx_rate flag."""
    from app.core import settings_store as ss_module
    fx = {"USD": 83.0, "EUR": 90.0, "GBP": 105.0, "SGD": 62.0, "AED": 22.6}
    supported = ["INR", "USD", "EUR", "GBP", "SGD", "AED"]
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.fx_rates_inr_per_unit": fx,
            "pricing.supported_currencies": supported,
        }.get(k, default))

    r = client.get("/api/v1/pricing/currencies")
    assert r.status_code == 200
    body = r.json()
    codes = [o["code"] for o in body["options"]]
    assert codes == ["INR", "USD", "EUR", "GBP", "SGD", "AED"]
    inr = next(o for o in body["options"] if o["code"] == "INR")
    assert inr["symbol"] == "₹"          # ₹
    assert inr["has_fx_rate"] is True


def test_list_currencies_flags_missing_fx_rate(client, db, monkeypatch):
    """Admin listed JPY in supported_currencies but forgot the FX rate.
    Endpoint surfaces has_fx_rate=false so the frontend can disable it."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.fx_rates_inr_per_unit": {"USD": 83.0},
            "pricing.supported_currencies": ["INR", "USD", "JPY"],
        }.get(k, default))

    r = client.get("/api/v1/pricing/currencies")
    body = r.json()
    jpy = next(o for o in body["options"] if o["code"] == "JPY")
    assert jpy["has_fx_rate"] is False


def test_quote_with_usd_currency_returns_display_block(client, db, monkeypatch):
    """End-to-end: POST /pricing/quote with currency=USD includes the
    display_* block + skips GST."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.fx_rates_inr_per_unit": {"USD": 83.0},
            "pricing.supported_currencies": ["INR", "USD"],
            "pricing.gst_percent": 18,
            "pricing.stack_offer_with_discount": False,
        }.get(k, default))
    _seed_plan(db, base=99900)

    r = client.post("/api/v1/pricing/quote", json={
        "plan_slug": "exam-bundle", "currency": "USD"})
    assert r.status_code == 200
    body = r.json()
    # INR breakdown still uses GST.
    assert body["gst_percent"] == 18
    assert body["gst_paise"] == 17982
    assert body["final_price_paise"] == 117882
    # USD display block uses subtotal (no GST) / fx_rate.
    assert body["display_currency"] == "USD"
    assert body["display_amount_minor"] == round(99900 / 83.0)
    assert body["display_fx_rate"] == 83.0
    assert body["display_currency_supported"] is True


def test_quote_with_default_currency_unchanged(client, db, monkeypatch):
    """REGRESSION GUARD: existing callers (production payment flow) that
    don't pass a currency must see the SAME response shape as before
    the currency feature shipped. display_* defaults to INR mirror."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.fx_rates_inr_per_unit": {"USD": 83.0},
            "pricing.supported_currencies": ["INR", "USD"],
            "pricing.gst_percent": 18,
            "pricing.stack_offer_with_discount": False,
        }.get(k, default))
    _seed_plan(db, base=99900)

    r = client.post("/api/v1/pricing/quote", json={"plan_slug": "exam-bundle"})
    body = r.json()
    assert body["final_price_paise"] == 117882    # subtotal + 18% GST
    assert body["display_currency"] == "INR"
    assert body["display_amount_minor"] == 117882  # mirrors INR final
    assert body["display_currency_supported"] is True


def test_quote_with_unsupported_currency_falls_back_with_flag(client, db, monkeypatch):
    """Unknown currency soft-fails — quote returns with the INR final
    in the display block AND display_currency_supported=false so the
    frontend can refuse checkout."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.fx_rates_inr_per_unit": {"USD": 83.0},
            "pricing.supported_currencies": ["INR", "USD"],
            "pricing.gst_percent": 0,
            "pricing.stack_offer_with_discount": False,
        }.get(k, default))
    _seed_plan(db, base=99900)

    r = client.post("/api/v1/pricing/quote", json={
        "plan_slug": "exam-bundle", "currency": "JPY"})
    body = r.json()
    assert body["display_currency_supported"] is False
    assert body["display_currency"] == "INR"
    assert body["display_amount_minor"] == 99900  # mirror of final
