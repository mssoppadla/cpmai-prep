"""PricingService unit tests.

Pure-logic suite. Uses the in-memory `db` fixture from conftest, but
every test seeds only what it needs (Plan + optional OfferCode) — no
HTTP, no users, no payments.

Coverage matrix:

  base only                     → final = base
  base + discount               → final = discount, stack-off
  base + offer (% or flat)      → final = base - offer
  base + discount + offer (off) → offer ignored (discount wins)
  base + discount + offer (on)  → final = discount - offer (stacked)

Plus eligibility cases:
  - missing code → soft fail, applied=false
  - inactive code
  - expired code (valid_until past)
  - not-yet-valid code (valid_from future)
  - max_redemptions reached
  - applies_to_plan_ids excludes this plan
  - percent capped to 0..100
  - flat clamped at the price (final >= 0)
"""
from datetime import datetime, timedelta, timezone
import pytest

from app.models.plan import Plan
from app.models.offer import OfferCode
from app.core.exceptions import NotFoundError, ValidationError
from app.services.pricing_service import PricingService


# -------------------------------------------------------------- helpers
def _make_plan(db, *, slug="exam-bundle", base=99900, discount=None,
                is_active=True) -> Plan:
    p = Plan(
        name=f"Plan {slug}", slug=slug, bundle_type="exam_bundle",
        base_price_paise=base, discount_price_paise=discount,
        currency="INR", duration_days=365, perks={},
        is_active=is_active, display_order=10,
    )
    db.add(p); db.commit(); db.refresh(p)
    return p


def _make_offer(db, *, code="SAVE10", kind="percent", value=10,
                 valid_from=None, valid_until=None,
                 max_redemptions=None, used_count=0,
                 applies_to_plan_ids=None, is_active=True) -> OfferCode:
    o = OfferCode(
        code=code.upper(), discount_type=kind, discount_value=value,
        valid_from=valid_from, valid_until=valid_until,
        max_redemptions=max_redemptions, used_count=used_count,
        applies_to_plan_ids=applies_to_plan_ids, is_active=is_active,
    )
    db.add(o); db.commit(); db.refresh(o)
    return o


@pytest.fixture
def stack_off(monkeypatch):
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: (False if k == "pricing.stack_offer_with_discount"
                                       else default))


@pytest.fixture
def stack_on(monkeypatch):
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: (True if k == "pricing.stack_offer_with_discount"
                                       else default))


# ============================================================== basics
def test_quote_base_only(db, stack_off):
    _make_plan(db, base=99900)
    q = PricingService(db).quote("exam-bundle")
    assert q.final_price_paise == 99900
    assert q.offer_applied is False
    assert q.discount_price_paise is None


def test_quote_with_discount_no_offer(db, stack_off):
    _make_plan(db, base=99900, discount=79900)
    q = PricingService(db).quote("exam-bundle")
    assert q.final_price_paise == 79900
    assert q.effective_before_offer_paise == 79900


def test_quote_unknown_plan_raises(db, stack_off):
    with pytest.raises(NotFoundError):
        PricingService(db).quote("does-not-exist")


def test_quote_inactive_plan_raises(db, stack_off):
    _make_plan(db, slug="hidden", is_active=False)
    with pytest.raises(NotFoundError):
        PricingService(db).quote("hidden")


def test_quote_misconfigured_zero_price_raises(db, stack_off):
    p = _make_plan(db)
    p.base_price_paise = 0
    db.commit()
    with pytest.raises(ValidationError):
        PricingService(db).quote(p.slug)


# ===================================================== offer math (off)
def test_offer_percent_applies_when_no_discount(db, stack_off):
    _make_plan(db, base=100_000)
    _make_offer(db, code="SAVE10", kind="percent", value=10)
    q = PricingService(db).quote("exam-bundle", "save10")
    assert q.offer_applied is True
    assert q.offer_discount_paise == 10_000
    assert q.final_price_paise == 90_000


def test_offer_flat_applies_when_no_discount(db, stack_off):
    _make_plan(db, base=99900)
    _make_offer(db, code="FLAT100", kind="flat", value=10_000)
    q = PricingService(db).quote("exam-bundle", "FLAT100")
    assert q.offer_discount_paise == 10_000
    assert q.final_price_paise == 89_900


def test_offer_ignored_when_discount_present_stack_off(db, stack_off):
    _make_plan(db, base=100_000, discount=80_000)
    _make_offer(db, code="SAVE20", kind="percent", value=20)
    q = PricingService(db).quote("exam-bundle", "save20")
    # Stack off + plan discount present → offer silently ignored.
    assert q.offer_applied is False
    assert q.offer_reason is not None
    assert q.final_price_paise == 80_000


# ===================================================== offer math (on)
def test_offer_stacks_with_discount_when_toggle_on(db, stack_on):
    _make_plan(db, base=100_000, discount=80_000)
    _make_offer(db, code="SAVE10", kind="percent", value=10)
    q = PricingService(db).quote("exam-bundle", "save10")
    # 10% off the discounted price (80,000 → 8,000 off → 72,000).
    assert q.offer_applied is True
    assert q.offer_discount_paise == 8_000
    assert q.final_price_paise == 72_000


def test_offer_stacks_with_no_discount_same_as_off(db, stack_on):
    # When there's no plan-level discount, stack-on/off should agree.
    _make_plan(db, base=100_000)
    _make_offer(db, code="SAVE10", kind="percent", value=10)
    q = PricingService(db).quote("exam-bundle", "save10")
    assert q.final_price_paise == 90_000


# ============================================================ clamping
def test_flat_offer_cannot_make_price_negative(db, stack_off):
    _make_plan(db, base=5_000)
    _make_offer(db, code="HUGE", kind="flat", value=999_999_999)
    q = PricingService(db).quote("exam-bundle", "huge")
    assert q.final_price_paise == 0
    assert q.offer_applied is True


def test_percent_clamped_high_treated_as_100(db, stack_off):
    _make_plan(db, base=10_000)
    _make_offer(db, code="OVER", kind="percent", value=150)
    q = PricingService(db).quote("exam-bundle", "over")
    assert q.offer_discount_paise == 10_000
    assert q.final_price_paise == 0


# =========================================================== eligibility
def test_unknown_offer_returns_soft_fail(db, stack_off):
    _make_plan(db, base=10_000)
    q = PricingService(db).quote("exam-bundle", "GHOST")
    assert q.offer_applied is False
    assert q.offer_reason == "Code not found."
    assert q.final_price_paise == 10_000


def test_inactive_offer_blocked(db, stack_off):
    _make_plan(db, base=10_000)
    _make_offer(db, code="OFF", is_active=False)
    q = PricingService(db).quote("exam-bundle", "off")
    assert q.offer_applied is False
    assert "inactive" in (q.offer_reason or "").lower()


def test_expired_offer_blocked(db, stack_off):
    _make_plan(db, base=10_000)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    _make_offer(db, code="OLD", valid_until=yesterday)
    q = PricingService(db).quote("exam-bundle", "old")
    assert q.offer_applied is False
    assert "expired" in (q.offer_reason or "").lower()


def test_not_yet_valid_offer_blocked(db, stack_off):
    _make_plan(db, base=10_000)
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    _make_offer(db, code="FUTURE", valid_from=tomorrow)
    q = PricingService(db).quote("exam-bundle", "future")
    assert q.offer_applied is False
    assert "not yet" in (q.offer_reason or "").lower()


def test_max_redemptions_reached_blocked(db, stack_off):
    _make_plan(db, base=10_000)
    _make_offer(db, code="LIMITED", max_redemptions=5, used_count=5)
    q = PricingService(db).quote("exam-bundle", "limited")
    assert q.offer_applied is False
    assert "limit" in (q.offer_reason or "").lower()


def test_offer_scoped_to_other_plans_blocked(db, stack_off):
    _make_plan(db, slug="exam-bundle", base=10_000)
    other = _make_plan(db, slug="course", base=50_000)
    _make_offer(db, code="COURSE",
                applies_to_plan_ids=[other.id])
    q = PricingService(db).quote("exam-bundle", "course")
    assert q.offer_applied is False
    assert "does not apply" in (q.offer_reason or "").lower()


def test_offer_scoped_to_this_plan_works(db, stack_off):
    p = _make_plan(db, base=10_000)
    _make_offer(db, code="HERE", kind="percent", value=10,
                applies_to_plan_ids=[p.id])
    q = PricingService(db).quote("exam-bundle", "here")
    assert q.offer_applied is True
    assert q.final_price_paise == 9_000


# ========================================================= reservation
def test_reserve_offer_increments_used_count(db, stack_off):
    o = _make_offer(db, code="X", max_redemptions=3, used_count=0)
    svc = PricingService(db)
    assert svc.reserve_offer_redemption(o.id) is True
    db.refresh(o); assert o.used_count == 1


def test_reserve_offer_blocked_when_cap_reached(db, stack_off):
    o = _make_offer(db, code="X", max_redemptions=3, used_count=3)
    assert PricingService(db).reserve_offer_redemption(o.id) is False


def test_release_offer_decrements_used_count(db, stack_off):
    o = _make_offer(db, code="X", used_count=5)
    PricingService(db).release_offer_redemption(o.id)
    db.refresh(o); assert o.used_count == 4


def test_release_offer_floors_at_zero(db, stack_off):
    o = _make_offer(db, code="X", used_count=0)
    PricingService(db).release_offer_redemption(o.id)
    db.refresh(o); assert o.used_count == 0


# =========================================== stack toggle is read each call
def test_stack_toggle_read_per_call(db, monkeypatch):
    """Switching the toggle must affect subsequent quotes without restart."""
    _make_plan(db, base=100_000, discount=80_000)
    _make_offer(db, code="SAVE10", kind="percent", value=10)
    flips = {"on": False}
    from app.core import settings_store as ss_module
    def fake_get(self, k, default=None):
        if k == "pricing.stack_offer_with_discount":
            return flips["on"]
        return default
    monkeypatch.setattr(ss_module.SettingsStore, "get", fake_get)

    q1 = PricingService(db).quote("exam-bundle", "save10")
    assert q1.offer_applied is False                    # stack off
    flips["on"] = True
    q2 = PricingService(db).quote("exam-bundle", "save10")
    assert q2.offer_applied is True                     # stack on now
    assert q2.final_price_paise == 72_000


# ====================================================== code normalisation
def test_offer_lookup_is_case_insensitive(db, stack_off):
    _make_plan(db, base=10_000)
    _make_offer(db, code="MIXED", kind="percent", value=10)
    q = PricingService(db).quote("exam-bundle", "mIxEd")
    assert q.offer_applied is True


def test_blank_offer_code_treated_as_no_offer(db, stack_off):
    _make_plan(db, base=10_000)
    q = PricingService(db).quote("exam-bundle", "   ")
    assert q.offer_applied is False
    assert q.offer_code is None
    assert q.final_price_paise == 10_000


# ============================================================== GST
@pytest.fixture
def gst_18(monkeypatch):
    """GST=18%, stack toggle off — for the standard Indian flow tests."""
    from app.core import settings_store as ss_module
    def fake_get(self, k, default=None):
        if k == "pricing.gst_percent": return 18
        if k == "pricing.stack_offer_with_discount": return False
        return default
    monkeypatch.setattr(ss_module.SettingsStore, "get", fake_get)


def test_gst_added_when_no_offer_or_discount(db, gst_18):
    _make_plan(db, base=100_000)            # ₹1,000
    q = PricingService(db).quote("exam-bundle")
    assert q.subtotal_paise == 100_000
    assert q.gst_percent == 18
    assert q.gst_paise == 18_000           # 18% of ₹1,000 = ₹180
    assert q.final_price_paise == 118_000


def test_gst_added_after_plan_discount(db, gst_18):
    _make_plan(db, base=100_000, discount=80_000)
    q = PricingService(db).quote("exam-bundle")
    # GST applies on the post-discount subtotal, not the base.
    assert q.subtotal_paise == 80_000
    assert q.gst_paise == 14_400          # 18% of ₹800 = ₹144
    assert q.final_price_paise == 94_400


def test_gst_added_after_offer(db, gst_18):
    _make_plan(db, base=100_000)
    _make_offer(db, code="SAVE10", kind="percent", value=10)
    q = PricingService(db).quote("exam-bundle", "save10")
    assert q.offer_applied is True
    assert q.subtotal_paise == 90_000     # 10% off ₹1,000 = ₹900
    assert q.gst_paise == 16_200          # 18% of ₹900 = ₹162
    assert q.final_price_paise == 106_200


def test_gst_zero_means_no_gst_line(db, monkeypatch):
    """When admin sets gst_percent=0, gst fields are 0 and final == subtotal."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: (
            0 if k == "pricing.gst_percent"
            else False if k == "pricing.stack_offer_with_discount"
            else default))
    _make_plan(db, base=100_000)
    q = PricingService(db).quote("exam-bundle")
    assert q.gst_percent == 0
    assert q.gst_paise == 0
    assert q.final_price_paise == q.subtotal_paise == 100_000


def test_gst_truncation_not_rounding(db, monkeypatch):
    """At odd amounts, integer truncation drops fractional paise.
    `subtotal=999, gst=18%` → 999*18//100 = 179 (not 180)."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: (
            18 if k == "pricing.gst_percent"
            else False if k == "pricing.stack_offer_with_discount"
            else default))
    _make_plan(db, base=999)
    q = PricingService(db).quote("exam-bundle")
    assert q.gst_paise == 179
    assert q.final_price_paise == 1178


def test_gst_clamped_to_0_to_100(db, monkeypatch):
    """Admin types 250% by mistake → service clamps to 100, never errors."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: (
            250 if k == "pricing.gst_percent"
            else False if k == "pricing.stack_offer_with_discount"
            else default))
    _make_plan(db, base=10_000)
    q = PricingService(db).quote("exam-bundle")
    assert q.gst_percent == 100            # clamped from 250
    assert q.final_price_paise == 20_000   # 10k subtotal + 10k GST


def test_gst_invalid_value_treated_as_zero(db, monkeypatch):
    """Garbage in settings (string, None) doesn't crash — defaults to 0."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: (
            "not-a-number" if k == "pricing.gst_percent"
            else False if k == "pricing.stack_offer_with_discount"
            else default))
    _make_plan(db, base=10_000)
    q = PricingService(db).quote("exam-bundle")
    assert q.gst_percent == 0
    assert q.final_price_paise == 10_000


def test_gst_zero_subtotal_means_zero_gst(db, gst_18):
    """100% off → subtotal=0 → GST on zero is zero, final stays zero."""
    _make_plan(db, base=10_000)
    _make_offer(db, code="ALL", kind="percent", value=100)
    q = PricingService(db).quote("exam-bundle", "all")
    assert q.subtotal_paise == 0
    assert q.gst_paise == 0
    assert q.final_price_paise == 0


# ============================================================ currencies
# International pricing — live FX (Frankfurter) + transparent markup +
# admin overrides. The display block in PriceQuote breaks out the
# markup as a separate "international processing fee" line so the
# buyer can see it on the receipt instead of having it baked into a
# weird-looking FX rate.

from datetime import datetime, timezone


@pytest.fixture
def fx_live_with_markup(monkeypatch):
    """Stack-off + GST 18% + live FX rates configured.

    Mocks the new live-FX settings:
      pricing.fx_live_raw          {"USD": 83.33, "EUR": 90.91}
      pricing.fx_live_fetched_at   now (so source=LIVE, not STALE)
      pricing.fx_markup_percent    5.0
      pricing.fx_overrides         {}
    """
    fresh = datetime.now(timezone.utc).isoformat()
    from app.core import settings_store as ss_module
    def _get(self, k, default=None):
        return {
            "pricing.stack_offer_with_discount": False,
            "pricing.gst_percent":               18,
            "pricing.fx_live_raw":               {"USD": 83.33, "EUR": 90.91},
            "pricing.fx_live_fetched_at":        fresh,
            "pricing.fx_markup_percent":         5.0,
            "pricing.fx_overrides":              {},
        }.get(k, default)
    monkeypatch.setattr(ss_module.SettingsStore, "get", _get)


def test_quote_default_currency_is_inr(db, fx_live_with_markup):
    """No currency argument -> INR. Display mirrors INR final, no markup."""
    _make_plan(db, base=99900)
    q = PricingService(db).quote("exam-bundle")
    assert q.display_currency == "INR"
    assert q.display_amount_minor == q.final_price_paise
    assert q.display_fx_rate == 1.0
    assert q.display_fx_source == "inr"
    assert q.display_markup_minor == 0
    assert q.display_currency_supported is True


def test_quote_in_usd_breaks_out_markup_as_fee(db, fx_live_with_markup):
    """Non-INR + LIVE source: subtotal at mid-market + markup as
    separate line + total = subtotal + markup. GST is dropped."""
    _make_plan(db, base=99900)
    q = PricingService(db).quote("exam-bundle", currency="USD")

    # INR breakdown unchanged (canonical for receipts).
    assert q.subtotal_paise == 99900
    assert q.gst_percent == 18
    assert q.gst_paise == (99900 * 18) // 100
    assert q.final_price_paise == 99900 + 17982

    # USD display block — broken out.
    assert q.display_currency == "USD"
    assert q.display_fx_source == "live"
    assert q.display_fx_rate_raw == 83.33
    assert q.display_markup_percent == 5.0

    expected_sub = round(99900 / 83.33)
    assert q.display_subtotal_minor == expected_sub
    expected_markup = round(expected_sub * 5.0 / 100.0)
    assert q.display_markup_minor == expected_markup
    assert q.display_amount_minor == expected_sub + expected_markup
    assert abs(q.display_fx_rate - 83.33 * 1.05) < 0.001


def test_quote_override_takes_priority_and_has_no_markup_line(db, monkeypatch):
    """Admin override beats live AND markup is NOT applied (admin's
    rate is final; they baked their own margin in if they wanted)."""
    fresh = datetime.now(timezone.utc).isoformat()
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.stack_offer_with_discount": False,
            "pricing.gst_percent": 18,
            "pricing.fx_live_raw":       {"USD": 83.33},
            "pricing.fx_live_fetched_at": fresh,
            "pricing.fx_markup_percent":  5.0,
            "pricing.fx_overrides":      {"USD": 90.0},
        }.get(k, default))
    _make_plan(db, base=99900)

    q = PricingService(db).quote("exam-bundle", currency="USD")
    assert q.display_fx_source == "override"
    assert q.display_fx_rate == 90.0
    assert q.display_fx_rate_raw is None
    assert q.display_markup_percent == 0.0
    assert q.display_markup_minor == 0
    assert q.display_amount_minor == 1110     # 99900 / 90
    assert q.display_subtotal_minor == 1110


def test_quote_stale_live_rate_flags_source(db, monkeypatch):
    """Last-fetched older than 7 days -> source=STALE. Still chargeable
    so the UI can warn rather than blocking sales."""
    from datetime import timedelta
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.stack_offer_with_discount": False,
            "pricing.gst_percent": 0,
            "pricing.fx_live_raw":       {"USD": 83.33},
            "pricing.fx_live_fetched_at": old,
            "pricing.fx_markup_percent":  5.0,
            "pricing.fx_overrides":      {},
        }.get(k, default))
    _make_plan(db, base=99900)
    q = PricingService(db).quote("exam-bundle", currency="USD")
    assert q.display_fx_source == "stale"
    assert q.display_currency_supported is True


def test_quote_unsupported_currency_falls_back_with_flag(db, fx_live_with_markup):
    """Currency with no live rate AND no override -> UNAVAILABLE.
    UI shows the INR final + display_currency_supported=False."""
    _make_plan(db, base=99900)
    q = PricingService(db).quote("exam-bundle", currency="JPY")
    assert q.display_currency == "INR"
    assert q.display_currency_supported is False
    assert q.display_fx_source == "unavailable"
    assert q.display_amount_minor == q.final_price_paise


def test_quote_currency_case_insensitive(db, fx_live_with_markup):
    """Lowercase 'usd' resolves to USD."""
    _make_plan(db, base=99900)
    q = PricingService(db).quote("exam-bundle", currency="usd")
    assert q.display_currency == "USD"
    assert q.display_currency_supported is True


def test_quote_offer_in_usd_applies_to_subtotal_then_converts(db, fx_live_with_markup):
    """Offer applied: post-offer SUBTOTAL is what gets converted.
    Discount benefit flows through to international buyers; markup
    still applies on top of the discounted subtotal."""
    _make_plan(db, base=100000)
    _make_offer(db, code="SAVE20", kind="percent", value=20)
    q = PricingService(db).quote("exam-bundle", "save20", currency="USD")
    assert q.offer_applied is True
    assert q.subtotal_paise == 80000
    assert q.display_subtotal_minor == round(80000 / 83.33)
    assert q.display_markup_minor == round(q.display_subtotal_minor * 5.0 / 100.0)


def test_quote_zero_markup_means_no_markup_line(db, monkeypatch):
    """markup=0 -> display amount equals subtotal-at-mid-market exactly."""
    fresh = datetime.now(timezone.utc).isoformat()
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.stack_offer_with_discount": False,
            "pricing.gst_percent": 0,
            "pricing.fx_live_raw":       {"USD": 83.33},
            "pricing.fx_live_fetched_at": fresh,
            "pricing.fx_markup_percent":  0.0,
            "pricing.fx_overrides":      {},
        }.get(k, default))
    _make_plan(db, base=99900)
    q = PricingService(db).quote("exam-bundle", currency="USD")
    assert q.display_markup_percent == 0.0
    assert q.display_markup_minor == 0
    assert q.display_amount_minor == q.display_subtotal_minor
    assert q.display_fx_rate == 83.33


def test_quote_inr_explicit_matches_inr_default(db, fx_live_with_markup):
    """currency='INR' explicit == omitting the parameter."""
    _make_plan(db, base=99900)
    a = PricingService(db).quote("exam-bundle")
    b = PricingService(db).quote("exam-bundle", currency="INR")
    assert a.to_dict() == b.to_dict()
