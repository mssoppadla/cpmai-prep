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


# ============================================== GST mode (optional/mandatory)
def _settings(monkeypatch, values: dict):
    """Patch SettingsStore.get with a dict of overrides; anything else
    falls through to the caller-supplied default (matching prod when a
    key is unseeded)."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(
        ss_module.SettingsStore, "get",
        lambda self, k, default=None: values.get(k, default))


def test_gst_mode_optional_suppresses_gst_entirely(db, monkeypatch):
    """mode=optional → percent AND amount report 0 (no line renders),
    even though gst_percent stays configured at 18 for later."""
    _settings(monkeypatch, {"pricing.gst_percent": 18,
                             "pricing.gst_mode": "optional",
                             "pricing.stack_offer_with_discount": False})
    _make_plan(db, base=100_000)
    q = PricingService(db).quote("exam-bundle")
    assert q.gst_percent == 0
    assert q.gst_paise == 0
    assert q.final_price_paise == q.subtotal_paise == 100_000


def test_gst_mode_mandatory_charges_configured_percent(db, monkeypatch):
    _settings(monkeypatch, {"pricing.gst_percent": 18,
                             "pricing.gst_mode": "mandatory",
                             "pricing.stack_offer_with_discount": False})
    _make_plan(db, base=100_000)
    q = PricingService(db).quote("exam-bundle")
    assert q.gst_percent == 18
    assert q.gst_paise == 18_000
    assert q.final_price_paise == 118_000


def test_gst_mode_unset_defaults_to_mandatory(db, gst_18):
    """Existing deployments have no gst_mode row — behavior must not
    change (GST keeps being charged)."""
    _make_plan(db, base=100_000)
    q = PricingService(db).quote("exam-bundle")
    assert q.gst_paise == 18_000


def test_gst_mode_garbage_value_fails_toward_mandatory(db, monkeypatch):
    """A bad value written directly to the store must not silently stop
    GST collection."""
    _settings(monkeypatch, {"pricing.gst_percent": 18,
                             "pricing.gst_mode": "maybe?",
                             "pricing.stack_offer_with_discount": False})
    _make_plan(db, base=100_000)
    q = PricingService(db).quote("exam-bundle")
    assert q.gst_paise == 18_000


# ============================================== processing fee pass-through
def test_processing_fee_added_on_top_of_gst(db, monkeypatch):
    """Fee computes on (subtotal + GST) — the base Razorpay's cut
    applies to. ₹1,000 + 18% GST = ₹1,180; 2% of that = ₹23.60."""
    _settings(monkeypatch, {"pricing.gst_percent": 18,
                             "pricing.processing_fee_percent": 2,
                             "pricing.stack_offer_with_discount": False})
    _make_plan(db, base=100_000)
    q = PricingService(db).quote("exam-bundle")
    assert q.gst_paise == 18_000
    assert q.processing_fee_percent == 2
    assert q.processing_fee_paise == 2_360      # 2% of 118_000
    assert q.final_price_paise == 120_360
    # INR display block charges the fee-inclusive final.
    assert q.display_amount_minor == 120_360


def test_processing_fee_without_gst(db, monkeypatch):
    """GST optional + fee on → fee computes on the bare subtotal."""
    _settings(monkeypatch, {"pricing.gst_percent": 18,
                             "pricing.gst_mode": "optional",
                             "pricing.processing_fee_percent": 2.36,
                             "pricing.stack_offer_with_discount": False})
    _make_plan(db, base=100_000)
    q = PricingService(db).quote("exam-bundle")
    assert q.gst_paise == 0
    assert q.processing_fee_paise == 2_360      # floor(100_000 × 2.36%)
    assert q.final_price_paise == 102_360


def test_processing_fee_zero_means_no_fee_line(db, gst_18):
    """Default (unseeded/0) → fee fields are 0, totals unchanged —
    existing deployments see no price change from this feature."""
    _make_plan(db, base=100_000)
    q = PricingService(db).quote("exam-bundle")
    assert q.processing_fee_percent == 0
    assert q.processing_fee_paise == 0
    assert q.final_price_paise == 118_000       # subtotal + GST only


def test_processing_fee_fractional_percent_floors_paise(db, monkeypatch):
    """Paise-truncation convention holds for float percents:
    999 × 2.36% = 23.57… → 23 paise, never rounded up."""
    _settings(monkeypatch, {"pricing.gst_percent": 0,
                             "pricing.processing_fee_percent": 2.36,
                             "pricing.stack_offer_with_discount": False})
    _make_plan(db, base=999)
    q = PricingService(db).quote("exam-bundle")
    assert q.processing_fee_paise == 23
    assert q.final_price_paise == 1_022


def test_processing_fee_clamped_and_garbage_safe(db, monkeypatch):
    """>50 clamps to 50; non-numeric garbage → 0, never crashes."""
    _settings(monkeypatch, {"pricing.gst_percent": 0,
                             "pricing.processing_fee_percent": 90,
                             "pricing.stack_offer_with_discount": False})
    _make_plan(db, base=10_000)
    q = PricingService(db).quote("exam-bundle")
    assert q.processing_fee_percent == 50
    assert q.processing_fee_paise == 5_000

    _settings(monkeypatch, {"pricing.gst_percent": 0,
                             "pricing.processing_fee_percent": "lots",
                             "pricing.stack_offer_with_discount": False})
    q2 = PricingService(db).quote("exam-bundle")
    assert q2.processing_fee_percent == 0
    assert q2.processing_fee_paise == 0


def test_processing_fee_label_configurable_with_fallback(db, monkeypatch):
    _settings(monkeypatch, {"pricing.processing_fee_percent": 2,
                             "pricing.processing_fee_label": "Transaction fee",
                             "pricing.stack_offer_with_discount": False})
    q = PricingService(db).quote(
        _make_plan(db, base=10_000).slug)
    assert q.processing_fee_label == "Transaction fee"

    _settings(monkeypatch, {"pricing.processing_fee_percent": 2,
                             "pricing.processing_fee_label": "   ",
                             "pricing.stack_offer_with_discount": False})
    q2 = PricingService(db).quote("exam-bundle")
    assert q2.processing_fee_label == "Payment processing fee"


def test_processing_fee_excluded_from_non_inr_charge(db, monkeypatch):
    """International buyers must NOT pay the domestic gateway fee (nor
    GST): the USD charge converts from the bare subtotal; fee/GST stay
    in the INR reference fields only."""
    now = datetime.now(timezone.utc).isoformat()
    _settings(monkeypatch, {
        "pricing.gst_percent": 18,
        "pricing.processing_fee_percent": 2,
        "pricing.stack_offer_with_discount": False,
        "pricing.supported_currencies": ["INR", "USD"],
        "pricing.fx_live_raw": {"USD": 100.0},
        "pricing.fx_live_fetched_at": now,
        "pricing.fx_markup_percent": 0.0,
        "pricing.fx_overrides": {},
    })
    _make_plan(db, base=100_000)                # ₹1,000
    q = PricingService(db).quote("exam-bundle", currency="USD")
    assert q.display_currency == "USD"
    # ₹1,000 at 100 INR/USD = $10.00 = 1000 cents — no GST, no fee.
    assert q.display_subtotal_minor == 1_000
    assert q.display_amount_minor == 1_000
    # INR reference still carries both for receipts/audit.
    assert q.gst_paise == 18_000
    assert q.processing_fee_paise == 2_360


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
    """No currency argument -> INR. Display mirrors INR final, no markup,
    and no whole-unit rounding (INR is paise-native and Razorpay-India
    accepts paise directly, so rounding does NOT apply)."""
    _make_plan(db, base=99900)
    q = PricingService(db).quote("exam-bundle")
    assert q.display_currency == "INR"
    assert q.display_amount_minor == q.final_price_paise
    assert q.display_fx_rate == 1.0
    assert q.display_fx_source == "inr"
    assert q.display_markup_minor == 0
    assert q.display_rounding_adjustment_minor == 0
    assert q.display_currency_supported is True


def test_quote_in_usd_breaks_out_markup_as_fee(db, fx_live_with_markup):
    """Non-INR + LIVE source: subtotal at mid-market + markup as
    separate line + rounding-to-whole-unit + total. GST is dropped.

    Razorpay-International requires whole-unit amounts for several
    currencies (GBP confirmed in prod), so we ceil the final to the
    next whole major unit and surface the delta as its own line."""
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

    expected_sub = round(99900 / 83.33)            # 1199
    assert q.display_subtotal_minor == expected_sub
    expected_markup = round(expected_sub * 5.0 / 100.0)   # 60
    assert q.display_markup_minor == expected_markup
    # Pre-rounding: 1199 + 60 = 1259 cents. Ceiled to next whole unit
    # = 1300 cents = $13.00 (rounding adjustment = 41 cents).
    pre_round = expected_sub + expected_markup
    import math
    rounded = math.ceil(pre_round / 100) * 100
    assert q.display_amount_minor == rounded == 1300
    assert q.display_rounding_adjustment_minor == rounded - pre_round == 41
    assert abs(q.display_fx_rate - 83.33 * 1.05) < 0.001


def test_quote_override_takes_priority_and_has_no_markup_line(db, monkeypatch):
    """Admin override beats live AND markup is NOT applied (admin's
    rate is final; they baked their own margin in if they wanted).
    But whole-unit rounding still applies — Razorpay International's
    integer-amount rule doesn't care which rate produced the number."""
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
    # Pre-rounding: 99900 / 90 = 1110 cents. Ceil to 1200 cents = $12.00.
    assert q.display_subtotal_minor == 1110
    assert q.display_amount_minor == 1200
    assert q.display_rounding_adjustment_minor == 90


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
    still applies on top of the discounted subtotal, then the total
    gets ceiled to whole-unit."""
    import math
    _make_plan(db, base=100000)
    _make_offer(db, code="SAVE20", kind="percent", value=20)
    q = PricingService(db).quote("exam-bundle", "save20", currency="USD")
    assert q.offer_applied is True
    assert q.subtotal_paise == 80000
    expected_sub = round(80000 / 83.33)
    expected_markup = round(expected_sub * 5.0 / 100.0)
    assert q.display_subtotal_minor == expected_sub
    assert q.display_markup_minor == expected_markup
    # Pre-round = sub + markup. display_amount = ceil to next whole unit.
    pre_round = expected_sub + expected_markup
    rounded = math.ceil(pre_round / 100) * 100
    assert q.display_amount_minor == rounded
    assert q.display_rounding_adjustment_minor == rounded - pre_round


def test_quote_zero_markup_means_no_markup_line(db, monkeypatch):
    """markup=0 -> display_markup_minor is 0. Whole-unit rounding
    still applies on the subtotal (it's a Razorpay-rail constraint,
    independent of fee policy)."""
    import math
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
    # Subtotal at mid-market, then ceiled.
    assert q.display_subtotal_minor == round(99900 / 83.33)   # 1199
    expected_round = math.ceil(q.display_subtotal_minor / 100) * 100
    assert q.display_amount_minor == expected_round           # 1200
    assert q.display_rounding_adjustment_minor == expected_round - q.display_subtotal_minor
    assert q.display_fx_rate == 83.33


def test_quote_inr_explicit_matches_inr_default(db, fx_live_with_markup):
    """currency='INR' explicit == omitting the parameter."""
    _make_plan(db, base=99900)
    a = PricingService(db).quote("exam-bundle")
    b = PricingService(db).quote("exam-bundle", currency="INR")
    assert a.to_dict() == b.to_dict()


def test_quote_inr_never_rounds_to_whole_unit(db, fx_live_with_markup):
    """INR is exempt from whole-unit rounding.

    Razorpay-India accepts paise directly in the ``amount`` field, so
    a ₹999.00 charge goes through as 99900 paise exactly — no need to
    ceil to ₹1000. This is a regression guard: international rounding
    must NOT bleed into the domestic flow.
    """
    _make_plan(db, base=99949)            # non-whole-rupee on purpose
    q = PricingService(db).quote("exam-bundle", currency="INR")
    # Paise stay as-is, no ceil-to-100, no rounding line.
    assert q.display_amount_minor == q.final_price_paise
    assert q.display_amount_minor == 99949 + ((99949 * 18) // 100)
    assert q.display_rounding_adjustment_minor == 0


def test_quote_non_inr_ceils_to_next_whole_unit(db, monkeypatch):
    """Razorpay International requires whole-unit amounts for several
    currencies (GBP confirmed in prod: a 0.89 GBP charge got billed
    as 1 GBP, breaking buyer trust). We pre-empt the mismatch by
    ceil-ing the final minor amount to the next whole major unit and
    surfacing the delta as ``display_rounding_adjustment_minor`` so
    the UI can show it as its own line on the receipt.
    """
    import math
    fresh = datetime.now(timezone.utc).isoformat()
    from app.core import settings_store as ss_module
    # GBP rate that produces a fractional-pence pre-round amount.
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.stack_offer_with_discount": False,
            "pricing.gst_percent": 0,
            "pricing.fx_live_raw":       {"GBP": 105.0},
            "pricing.fx_live_fetched_at": fresh,
            "pricing.fx_markup_percent":  5.0,
            "pricing.fx_overrides":      {},
        }.get(k, default))
    _make_plan(db, base=89000)        # ₹890 -> ~£8.48 -> ceil to £9.00

    q = PricingService(db).quote("exam-bundle", currency="GBP")
    sub = round(89000 / 105.0)                       # 848
    markup = round(sub * 5.0 / 100.0)                # 42
    pre_round = sub + markup                         # 890 pence
    rounded = math.ceil(pre_round / 100) * 100       # 900 pence = £9.00
    assert q.display_subtotal_minor == sub
    assert q.display_markup_minor == markup
    assert q.display_amount_minor == rounded
    assert q.display_rounding_adjustment_minor == rounded - pre_round
    # Sanity: amount must be cleanly divisible by 100 (whole units).
    assert q.display_amount_minor % 100 == 0


def test_quote_non_inr_already_whole_unit_no_rounding(db, monkeypatch):
    """If the pre-round amount already lands on a whole major unit,
    ``display_rounding_adjustment_minor`` stays 0 — no spurious line
    added to the receipt."""
    fresh = datetime.now(timezone.utc).isoformat()
    from app.core import settings_store as ss_module
    # Rate engineered so 100000 paise * (1+0) / 100.0 = exactly 1000 cents.
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.stack_offer_with_discount": False,
            "pricing.gst_percent": 0,
            "pricing.fx_live_raw":       {"USD": 100.0},
            "pricing.fx_live_fetched_at": fresh,
            "pricing.fx_markup_percent":  0.0,
            "pricing.fx_overrides":      {},
        }.get(k, default))
    _make_plan(db, base=100000)
    q = PricingService(db).quote("exam-bundle", currency="USD")
    assert q.display_amount_minor == 1000
    assert q.display_rounding_adjustment_minor == 0
