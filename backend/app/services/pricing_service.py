"""Server-side price computation engine.

Single source of truth for "what does a Plan + OfferCode cost?". Every
endpoint that computes a price (public quote, order create, admin
preview) goes through here so frontend and backend never disagree.

Returned `PriceQuote` is intentionally a plain dataclass — easy to
serialise to JSON, easy to assert on in tests, never holds session.

Computation order:

  1. effective_before_offer = discount_price (if set) else base_price
  2. apply offer code (subject to the stacking toggle below) → subtotal
  3. add GST on the subtotal → final price (what the user pays / Razorpay
     order amount)

Stacking semantics (governed by `pricing.stack_offer_with_discount`):

  • Off (default):
      - If plan has a `discount_price`, that wins. Offer code is silently
        ignored, `applied=false` returned in the breakdown so UI can
        show "your discount is already better than this code".
      - If plan has NO `discount_price`, the offer applies to base_price.
  • On:
      - Effective price starts at `discount_price` if present else
        `base_price`. The offer code is then applied on top.

GST (`pricing.gst_percent`, default 18) is applied on the post-offer
subtotal — but ONLY for INR-currency checkouts. International
customers paying in USD/EUR/etc. do not pay Indian GST (it's a
domestic India tax). Set the percent to 0 to disable GST entirely
(no line item shown). Indian rounding convention: integer paise
truncation (`subtotal * pct // 100`) — sufficient at typical price
points; revisit if precise-rupee invoicing is ever required.

Subtotal is clamped to >= 0; GST on a zero subtotal is zero.

International currency support
------------------------------
Plans are denominated in INR (``Plan.base_price_paise``). When the
caller passes ``currency != "INR"``, the quote also includes a
``display_*`` block with:

  * the same plan converted to the target currency's minor units
    (cents for USD/EUR, fils for AED, etc. — all 1:100 for the
    currencies we support)
  * GST omitted (international customers don't pay Indian GST)
  * the FX rate used (INR per 1 unit of target currency)

The conversion is ``display_amount_minor = round(subtotal_paise / fx_rate)``.
Same minor-unit math as paise — relies on the 1:100 subunit shape
which holds for all currencies in our default supported set.

The display block is what gets passed to Razorpay's order.create when
the user pays in a non-INR currency. The INR breakdown is shown
alongside as a reference but isn't part of the charge in that case.

FX rates live in ``pricing.fx_rates_inr_per_unit`` (admin-editable).
Supported currencies live in ``pricing.supported_currencies``.
"""
import math
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.settings_store import settings_store
from app.models.plan import Plan
from app.models.offer import OfferCode
from app.services.fx import get_effective_rate, RateSource


# All currencies we support have a 1:100 minor:major ratio (cents/pence/
# fils/paise/etc.) — the same shape Razorpay expects in the `amount`
# field. JPY/KRW/IDR are not in our picker; if added, this constant
# needs to become per-currency.
_MINOR_UNITS_PER_MAJOR = 100


def _ceil_to_whole_unit(amount_minor: int) -> int:
    """Round amount_minor UP to the next whole major unit.

    1234 (cents) → 1300 (= $13.00)
    1200 (cents) → 1200 (already a whole unit, no change)
    0    (cents) → 0    (zero is a whole unit)

    Used to satisfy Razorpay International's integer-amount rule for
    non-INR charges. See PriceQuote.display_rounding_adjustment_minor
    for context.
    """
    if amount_minor <= 0:
        return 0
    return math.ceil(amount_minor / _MINOR_UNITS_PER_MAJOR) * _MINOR_UNITS_PER_MAJOR


@dataclass
class PriceQuote:
    plan_id: int
    plan_slug: str
    plan_name: str
    currency: str

    base_price_paise: int
    discount_price_paise: Optional[int]

    # Pre-offer effective price (= discount_price_paise if set, else
    # base_price_paise). What the offer is computed against when the
    # stack toggle is on.
    effective_before_offer_paise: int

    # Offer breakdown
    offer_code: Optional[str]
    offer_applied: bool
    offer_reason: Optional[str]   # human-readable why-not when applied=False
    offer_discount_paise: int     # 0 when applied=False

    # Subtotal (post-offer, pre-GST) — what GST is computed against.
    subtotal_paise: int

    # GST breakdown — gst_percent==0 means "no GST line shown".
    # NOTE: gst_paise is 0 when display_currency != "INR" (international
    # customers don't pay Indian GST). gst_percent is still reported as
    # the configured setting so the UI can decide whether to render the
    # row.
    gst_percent: int
    gst_paise: int

    # Final INR price the user pays IF they're paying in INR
    # (= subtotal + gst). This is the amount passed to Razorpay's
    # order.create call when currency == "INR".
    final_price_paise: int

    # The combine-toggle that was in effect at quote time. Stored on
    # Payment so audits can prove which mode produced the charge.
    stack_offer_with_discount: bool

    # ----- Display-currency block (added 2026-05-14) ---------------
    # The currency the CALLER asked us to compute for. May equal the
    # plan's native currency (INR), in which case the display_* fields
    # mirror the INR block above.
    display_currency: str = "INR"

    # Final amount in the display currency, in MINOR units (cents for
    # USD/EUR, fils for AED, paise for INR). This is what Razorpay's
    # ``amount`` field gets when ``display_currency`` is passed as
    # ``currency`` to order.create.
    #
    # = display_subtotal_minor + display_markup_minor
    # (for INR this equals final_price_paise which already includes GST)
    display_amount_minor: int = 0

    # FX rate USED for the conversion. For LIVE source this is the
    # MARKED-UP rate (= raw × (1 + markup/100)). For OVERRIDE source
    # this is the admin's rate as-is. 1.0 for INR. None if no rate
    # available (display_currency_supported=False).
    display_fx_rate: Optional[float] = 1.0

    # Raw mid-market rate (pre-markup). Set only when source=LIVE/STALE
    # — the frontend shows this as a "live FX rate" footnote.
    display_fx_rate_raw: Optional[float] = None

    # False if the caller asked for a currency we can't quote (not in
    # supported list, no FX rate, no override). Frontend should refuse
    # checkout. For INR + supported live + supported override: True.
    display_currency_supported: bool = True

    # Where the FX rate came from — drives the rate-provenance footnote
    # in the UI. One of: "inr", "live", "override", "stale", "unavailable".
    display_fx_source: str = "inr"

    # When the live rate was fetched (LIVE/STALE source only).
    display_fx_fetched_at: Optional[datetime] = None

    # ----- Transparent international-processing fee (broken out so the
    # user sees it as a separate line, not buried in the FX rate) -----
    #
    # Only non-zero for non-INR currencies with source=LIVE/STALE.
    # For source=OVERRIDE or INR, markup is 0 (admin's rate IS final,
    # or domestic INR doesn't need an FX fee).
    #
    # The math:
    #   display_subtotal_minor = round(subtotal_paise / raw_fx_rate)
    #     ← what the buyer would pay at pure mid-market rate
    #   display_markup_minor   = round(display_subtotal_minor × markup_percent/100)
    #     ← the international-processing fee, transparent
    #   display_amount_minor   = display_subtotal_minor + display_markup_minor
    #     ← total charged on the card
    display_subtotal_minor: int = 0
    display_markup_percent: float = 0.0
    display_markup_minor: int = 0

    # ----- Whole-unit rounding adjustment (Razorpay International) -----
    #
    # Razorpay's International rail rounds (or rejects) non-whole-unit
    # amounts for several currencies — GBP confirmed in production
    # (charge of 0.89 GBP got billed as 1 GBP, breaking buyer trust).
    # Fix: ceil the final non-INR amount to the next whole currency
    # unit (cents -> next 100) at quote-time so the displayed total
    # and the charged total always match.
    #
    # Surfaced as a SEPARATE line in the breakdown so the buyer sees
    # exactly where the small adjustment came from instead of finding
    # it baked silently into the rate or fee.
    #
    # Zero for INR (paise are valid Razorpay-India amounts) and for
    # UNAVAILABLE (we fall back to INR). Non-zero for LIVE/STALE/OVERRIDE.
    display_rounding_adjustment_minor: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class PricingService:
    """Stateless on the surface — takes a session for OfferCode lookups
    only. All numeric work is pure."""

    def __init__(self, db: Session):
        self.db = db

    # --------------------------------------------------------- public API
    def quote(self, plan_slug: str,
              offer_code: Optional[str] = None,
              currency: str = "INR") -> PriceQuote:
        """Compute the price the user would pay right now for plan_slug.

        Args:
            plan_slug: which Plan to price
            offer_code: optional offer code to apply
            currency: what currency to compute the display block in.
                Defaults to "INR" (the plan's native currency). If
                provided and supported, the result includes ``display_*``
                fields with the converted amount. If the currency is
                unsupported (not in ``pricing.supported_currencies`` or
                no FX rate configured), we silently fall back to INR
                AND set ``display_currency_supported=False`` so the
                caller can decide how to handle it (typically: block
                checkout in that currency).

        Raises:
            NotFoundError: if the plan doesn't exist or is inactive.

        Soft failures (returned as a quote with explanatory fields):
            * invalid/expired offer code
            * currency not in supported set

        These are deliberately NOT exceptions — the UI wants to render
        the underlying INR price even when one of these warnings applies.
        """
        plan = self._load_plan(plan_slug)
        stack = self._stack_toggle()

        effective_before_offer = (plan.discount_price_paise
                                  if plan.discount_price_paise is not None
                                  else plan.base_price_paise)

        # Treat blank/whitespace input the same as no code at all — no
        # warning shown to the user.
        normalised_code = (offer_code or "").strip().upper()
        if not normalised_code:
            return self._build_quote(
                plan=plan,
                effective_before_offer=effective_before_offer,
                offer_code=None, offer_applied=False, offer_reason=None,
                offer_discount=0,
                subtotal=effective_before_offer,
                stack=stack,
                target_currency=currency,
            )

        # Look up code (case-insensitive, trimmed). A missing code is a
        # soft failure — quote still returns, breakdown explains.
        code = self._load_offer(normalised_code)
        if code is None:
            return self._build_quote(
                plan=plan,
                effective_before_offer=effective_before_offer,
                offer_code=normalised_code, offer_applied=False,
                offer_reason="Code not found.",
                offer_discount=0,
                subtotal=effective_before_offer,
                stack=stack,
                target_currency=currency,
            )

        ineligibility = self._eligibility_reason(code, plan)
        if ineligibility:
            return self._build_quote(
                plan=plan,
                effective_before_offer=effective_before_offer,
                offer_code=normalised_code, offer_applied=False,
                offer_reason=ineligibility,
                offer_discount=0,
                subtotal=effective_before_offer,
                stack=stack,
                target_currency=currency,
            )

        # Stack-toggle off + plan has a discount → ignore offer.
        if not stack and plan.discount_price_paise is not None:
            return self._build_quote(
                plan=plan,
                effective_before_offer=effective_before_offer,
                offer_code=normalised_code, offer_applied=False,
                offer_reason=("Plan discount is already applied; offer "
                              "codes do not stack with discounts."),
                offer_discount=0,
                subtotal=effective_before_offer,
                stack=stack,
                target_currency=currency,
            )

        # Apply the offer.
        target = (effective_before_offer if stack
                  else plan.base_price_paise)
        discount = self._compute_discount_paise(code, target)
        subtotal = max(0, effective_before_offer - discount) if stack \
                else max(0, plan.base_price_paise - discount)

        return self._build_quote(
            plan=plan,
            effective_before_offer=effective_before_offer,
            offer_code=code.code, offer_applied=True, offer_reason=None,
            offer_discount=discount,
            subtotal=subtotal,
            stack=stack,
            target_currency=currency,
        )

    def reserve_offer_redemption(self, code_id: int) -> bool:
        """Atomically increment an offer's used_count when its cap allows.

        Returns True if reserved, False if the cap is hit. Caller must
        roll back the seat if the surrounding transaction (e.g. the
        payment order create) fails — see release_offer_redemption.
        """
        code = self.db.get(OfferCode, code_id)
        if code is None or not code.is_active:
            return False
        if code.max_redemptions is not None \
                and code.used_count >= code.max_redemptions:
            return False
        code.used_count += 1
        self.db.flush()
        return True

    def release_offer_redemption(self, code_id: int) -> None:
        """Best-effort decrement when a reservation didn't lead to a sale."""
        code = self.db.get(OfferCode, code_id)
        if code is None: return
        code.used_count = max(0, (code.used_count or 0) - 1)
        self.db.flush()

    # --------------------------------------------------------- internals
    def _load_plan(self, slug: str) -> Plan:
        plan = (self.db.query(Plan)
                .filter_by(slug=slug, is_active=True).first())
        if plan is None:
            raise NotFoundError(f"Plan '{slug}' not found.")
        if plan.base_price_paise is None or plan.base_price_paise <= 0:
            raise ValidationError(f"Plan '{slug}' is misconfigured "
                                   f"(base_price_paise must be > 0).")
        return plan

    def _load_offer(self, raw_code: str) -> Optional[OfferCode]:
        code = (raw_code or "").strip().upper()
        if not code:
            return None
        return (self.db.query(OfferCode)
                .filter(OfferCode.code == code).first())

    def _eligibility_reason(self, code: OfferCode, plan: Plan
                             ) -> Optional[str]:
        if not code.is_active:
            return "Code is inactive."
        now = datetime.now(timezone.utc)
        if code.valid_from and code.valid_from > now:
            return "Code is not yet valid."
        if code.valid_until and code.valid_until < now:
            return "Code has expired."
        if code.max_redemptions is not None \
                and (code.used_count or 0) >= code.max_redemptions:
            return "Code redemption limit reached."
        if code.applies_to_plan_ids:
            if plan.id not in code.applies_to_plan_ids:
                return "Code does not apply to this plan."
        return None

    @staticmethod
    def _compute_discount_paise(code: OfferCode, target_paise: int) -> int:
        if code.discount_type == "percent":
            pct = max(0, min(100, code.discount_value))
            return (target_paise * pct) // 100
        if code.discount_type == "flat":
            return min(target_paise, max(0, code.discount_value))
        return 0   # unknown type — treat as no-op

    @staticmethod
    def _stack_toggle() -> bool:
        v = settings_store.get("pricing.stack_offer_with_discount", False)
        return bool(v)

    @staticmethod
    def _gst_percent() -> int:
        """0..100 admin-configurable GST. Clamped defensively in case an
        admin types something out-of-range into Runtime Settings."""
        try:
            v = int(settings_store.get("pricing.gst_percent", 0) or 0)
        except (TypeError, ValueError):
            v = 0
        return max(0, min(100, v))

    @staticmethod
    def _supported_currencies() -> list[str]:
        """The currencies the /pricing picker can offer.

        Returns the configured set normalised to uppercase, with INR
        guaranteed-included even if an admin mis-edits the setting
        (we never want to lock ourselves out of the canonical
        currency)."""
        raw = settings_store.get("pricing.supported_currencies",
                                  ["INR", "USD"])
        if not isinstance(raw, list):
            return ["INR"]
        codes = []
        for c in raw:
            if isinstance(c, str) and len(c.strip()) == 3:
                u = c.strip().upper()
                if u not in codes:
                    codes.append(u)
        if "INR" not in codes:
            codes.insert(0, "INR")
        return codes

    @staticmethod
    def _fx_rates() -> dict[str, float]:
        """INR-per-1-unit-of-currency map. Defensive defaults so a
        missing setting doesn't crash quote generation — currencies
        without a rate are marked unsupported in the quote response."""
        raw = settings_store.get("pricing.fx_rates_inr_per_unit", {})
        rates: dict[str, float] = {"INR": 1.0}
        if not isinstance(raw, dict):
            return rates
        for code, rate in raw.items():
            if not isinstance(code, str) or len(code.strip()) != 3:
                continue
            try:
                f = float(rate)
                if f > 0:
                    rates[code.strip().upper()] = f
            except (TypeError, ValueError):
                continue
        return rates

    @staticmethod
    def _build_display_block(target_currency: str,
                              subtotal_paise: int,
                              final_inr_paise: int) -> dict:
        """Compute the display-currency block of a PriceQuote.

        Returns a dict keyed to match PriceQuote's ``display_*`` fields.
        Caller spreads this into the dataclass constructor.

        Source priority (delegated to fx.get_effective_rate):
          1. OVERRIDE (admin lock) — rate as-is, markup=0
          2. LIVE (Frankfurter + markup) — markup broken out as fee
          3. STALE (last-known live, >7 days) — same shape as LIVE
             but display_fx_source="stale" so UI can warn
          4. INR — passthrough, mirrors the INR final
          5. UNAVAILABLE — fall back to INR final, supported=False

        GST is INR-only — non-INR display converts from the pre-GST
        ``subtotal_paise``. International customers don't pay Indian GST.

        Math (non-INR with LIVE source):
            raw_rate          = e.g. 83.33 INR/USD (Frankfurter)
            markup_percent    = 5
            sub_minor         = round(subtotal_paise / raw_rate)    ← mid-market base
            markup_minor      = round(sub_minor × markup_percent / 100)
            amount_minor      = sub_minor + markup_minor              ← charged to card
            effective_rate    = raw_rate × (1 + markup_percent/100)
        """
        target = (target_currency or "INR").strip().upper()
        rate = get_effective_rate(target)

        if rate.source == RateSource.INR:
            return {
                "display_currency": "INR",
                "display_amount_minor": final_inr_paise,
                "display_fx_rate": 1.0,
                "display_fx_rate_raw": None,
                "display_currency_supported": True,
                "display_fx_source": "inr",
                "display_fx_fetched_at": None,
                "display_subtotal_minor": final_inr_paise,
                "display_markup_percent": 0.0,
                "display_markup_minor": 0,
                "display_rounding_adjustment_minor": 0,
            }

        if rate.source == RateSource.UNAVAILABLE:
            # No way to quote this currency. Mirror INR + flag so UI
            # refuses checkout. No rounding adjustment — we're not
            # actually going to charge in this currency.
            return {
                "display_currency": "INR",
                "display_amount_minor": final_inr_paise,
                "display_fx_rate": 1.0,
                "display_fx_rate_raw": None,
                "display_currency_supported": False,
                "display_fx_source": "unavailable",
                "display_fx_fetched_at": None,
                "display_subtotal_minor": final_inr_paise,
                "display_markup_percent": 0.0,
                "display_markup_minor": 0,
                "display_rounding_adjustment_minor": 0,
            }

        if rate.source == RateSource.OVERRIDE:
            # Admin set this rate directly. Treat their value as final
            # — no markup line shown (the admin baked it in if they
            # wanted). Convert from pre-GST subtotal (no Indian GST).
            #
            # Ceil to whole-unit (see Razorpay-International rounding
            # block at end of method).
            raw_amount = int(round(subtotal_paise / rate.inr_per_unit))
            rounded = _ceil_to_whole_unit(raw_amount)
            rounding_adj = rounded - raw_amount
            return {
                "display_currency": target,
                "display_amount_minor": rounded,
                "display_fx_rate": rate.inr_per_unit,
                "display_fx_rate_raw": None,
                "display_currency_supported": True,
                "display_fx_source": "override",
                "display_fx_fetched_at": None,
                "display_subtotal_minor": raw_amount,
                "display_markup_percent": 0.0,
                "display_markup_minor": 0,
                "display_rounding_adjustment_minor": rounding_adj,
            }

        # LIVE or STALE: raw mid-market rate + transparent markup line.
        raw = rate.raw_inr_per_unit or rate.inr_per_unit
        markup = rate.markup_percent or 0.0
        # Subtotal at pure mid-market rate.
        sub_minor = int(round(subtotal_paise / raw))
        # Markup line. Computed on the SUBTOTAL (post-conversion) so the
        # 5% is "5% of what you'd pay at mid-market" — that's the right
        # mental model for a buyer reading the receipt.
        markup_minor = int(round(sub_minor * markup / 100.0))
        pre_round = sub_minor + markup_minor
        # Razorpay-International rule: amount must be a whole unit for
        # currencies like GBP (rounding/rejecting fractional charges in
        # production). Ceil up to keep the displayed total honest — the
        # delta is shown as a separate "Rounded to whole unit" line.
        rounded = _ceil_to_whole_unit(pre_round)
        rounding_adj = rounded - pre_round
        return {
            "display_currency": target,
            "display_amount_minor": rounded,
            "display_fx_rate": rate.inr_per_unit,
            "display_fx_rate_raw": raw,
            "display_currency_supported": True,
            "display_fx_source": rate.source.value,   # "live" or "stale"
            "display_fx_fetched_at": rate.fetched_at,
            "display_subtotal_minor": sub_minor,
            "display_markup_percent": markup,
            "display_markup_minor": markup_minor,
            "display_rounding_adjustment_minor": rounding_adj,
        }

    @classmethod
    def _build_quote(cls, *, plan: Plan, effective_before_offer: int,
                     offer_code, offer_applied, offer_reason,
                     offer_discount, subtotal, stack,
                     target_currency: str = "INR") -> PriceQuote:
        gst_percent = cls._gst_percent()
        # Integer truncation matches "drop fractional paise" — sufficient
        # for sub-rupee accuracy at our price points. If we ever issue
        # GSTIN-bearing invoices we'll need exact rounding rules.
        gst_paise = (subtotal * gst_percent) // 100
        final_price = subtotal + gst_paise
        display = cls._build_display_block(target_currency, subtotal, final_price)
        return PriceQuote(
            plan_id=plan.id, plan_slug=plan.slug, plan_name=plan.name,
            currency=plan.currency,
            base_price_paise=plan.base_price_paise,
            discount_price_paise=plan.discount_price_paise,
            effective_before_offer_paise=effective_before_offer,
            offer_code=offer_code,
            offer_applied=offer_applied,
            offer_reason=offer_reason,
            offer_discount_paise=offer_discount,
            subtotal_paise=subtotal,
            gst_percent=gst_percent,
            gst_paise=gst_paise,
            final_price_paise=final_price,
            stack_offer_with_discount=stack,
            **display,
        )
