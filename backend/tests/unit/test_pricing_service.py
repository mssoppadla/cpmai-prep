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
