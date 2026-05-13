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
# These tests use the NEW live-FX system (pricing.fx_live_raw +
# pricing.fx_markup_percent), not the legacy fx_rates_inr_per_unit
# which is now an empty/deprecated setting.

from datetime import datetime, timezone


def _mock_fx_live(monkeypatch, *, rates: dict, markup: float = 5.0,
                   overrides: dict | None = None, gst: int = 0,
                   supported_filter: list | None = None):
    """Helper: monkeypatch settings_store.get to return live FX state."""
    fresh = datetime.now(timezone.utc).isoformat()
    state = {
        "pricing.stack_offer_with_discount": False,
        "pricing.gst_percent":               gst,
        "pricing.fx_live_raw":               rates,
        "pricing.fx_live_fetched_at":        fresh,
        "pricing.fx_markup_percent":         markup,
        "pricing.fx_overrides":              overrides or {},
    }
    if supported_filter is not None:
        state["pricing.supported_currencies"] = supported_filter
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: state.get(k, default))


def test_list_currencies_returns_codes_with_live_rates(client, db, monkeypatch):
    """The picker offers currencies that have either a live rate OR
    an admin override. INR is always present."""
    _mock_fx_live(monkeypatch, rates={"USD": 83.33, "EUR": 90.91},
                   overrides={"AED": 22.6})
    r = client.get("/api/v1/pricing/currencies")
    assert r.status_code == 200
    body = r.json()
    codes = sorted(o["code"] for o in body["options"])
    assert "INR" in codes
    assert "USD" in codes
    assert "EUR" in codes
    assert "AED" in codes  # via override


def test_list_currencies_with_no_live_rates_only_shows_inr(client, db, monkeypatch):
    """Fresh deploy: no cron has run yet, no admin overrides. The
    picker only offers INR — frontend hides the dropdown entirely."""
    _mock_fx_live(monkeypatch, rates={}, overrides={})
    r = client.get("/api/v1/pricing/currencies")
    body = r.json()
    codes = [o["code"] for o in body["options"]]
    assert codes == ["INR"]


def test_quote_with_usd_currency_breaks_out_markup(client, db, monkeypatch):
    """End-to-end: POST /pricing/quote with currency=USD includes
    the broken-out markup line + skips Indian GST."""
    _mock_fx_live(monkeypatch, rates={"USD": 83.33}, markup=5.0, gst=18)
    _seed_plan(db, base=99900)

    r = client.post("/api/v1/pricing/quote", json={
        "plan_slug": "exam-bundle", "currency": "USD"})
    assert r.status_code == 200
    body = r.json()
    # INR breakdown still includes GST (canonical reference).
    assert body["gst_percent"] == 18
    assert body["gst_paise"] == 17982
    assert body["final_price_paise"] == 117882
    # USD display block — subtotal + markup = total.
    assert body["display_currency"] == "USD"
    assert body["display_fx_source"] == "live"
    assert body["display_fx_rate_raw"] == 83.33
    assert body["display_markup_percent"] == 5.0
    import math
    expected_sub = round(99900 / 83.33)
    expected_markup = round(expected_sub * 5.0 / 100.0)
    pre_round = expected_sub + expected_markup
    expected_total = math.ceil(pre_round / 100) * 100   # ceil to whole unit
    assert body["display_subtotal_minor"] == expected_sub
    assert body["display_markup_minor"] == expected_markup
    # Razorpay-International requires whole-unit amounts for several
    # currencies (GBP confirmed in prod). The /pricing/quote response
    # surfaces both the pre-round components and the post-round total.
    assert body["display_amount_minor"] == expected_total
    assert body["display_amount_minor"] % 100 == 0
    assert body["display_rounding_adjustment_minor"] == expected_total - pre_round
    assert body["display_currency_supported"] is True


def test_quote_with_default_currency_unchanged(client, db, monkeypatch):
    """REGRESSION GUARD: existing INR-only callers see no behavior
    change. Display block mirrors the INR final."""
    _mock_fx_live(monkeypatch, rates={"USD": 83.33}, markup=5.0, gst=18)
    _seed_plan(db, base=99900)

    r = client.post("/api/v1/pricing/quote", json={"plan_slug": "exam-bundle"})
    body = r.json()
    assert body["final_price_paise"] == 117882
    assert body["display_currency"] == "INR"
    assert body["display_amount_minor"] == 117882
    assert body["display_fx_source"] == "inr"
    assert body["display_markup_minor"] == 0
    # INR is exempt from whole-unit ceiling (Razorpay-India accepts
    # paise directly — only Razorpay-International has the rule).
    assert body["display_rounding_adjustment_minor"] == 0
    assert body["display_currency_supported"] is True


def test_quote_with_unsupported_currency_falls_back_with_flag(client, db, monkeypatch):
    """Currency without a live rate or override → UNAVAILABLE.
    Returns INR final + display_currency_supported=false; frontend
    refuses checkout."""
    _mock_fx_live(monkeypatch, rates={"USD": 83.33})
    _seed_plan(db, base=99900)

    r = client.post("/api/v1/pricing/quote", json={
        "plan_slug": "exam-bundle", "currency": "JPY"})
    body = r.json()
    assert body["display_currency_supported"] is False
    assert body["display_currency"] == "INR"
    assert body["display_fx_source"] == "unavailable"


