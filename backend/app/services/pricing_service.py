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
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.settings_store import settings_store
from app.models.plan import Plan
from app.models.offer import OfferCode


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
    # Computed as:
    #   * INR: equals final_price_paise (includes GST)
    #   * other: round(subtotal_paise / fx_rate)
    #           ↑ GST is INTENTIONALLY skipped for non-INR (Indian
    #             GST does not apply to international customers).
    display_amount_minor: int = 0

    # FX rate that was used to compute display_amount_minor.
    # Expressed as "INR per 1 unit of display_currency"
    # (e.g. 83 means 1 USD = 83 INR). 1.0 for INR. None if the
    # caller asked for an unsupported currency (we fall back to INR
    # and report ``display_currency_supported=False``).
    display_fx_rate: Optional[float] = 1.0

    # False if the caller asked for a currency NOT in
    # pricing.supported_currencies (or with no FX rate configured).
    # In that case the display block is identical to the INR block and
    # the front-end should refuse to checkout in that currency.
    display_currency_supported: bool = True

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

    @classmethod
    def _build_display_block(cls, target_currency: str,
                              subtotal_paise: int,
                              final_inr_paise: int
                              ) -> tuple[str, int, Optional[float], bool]:
        """Compute the (currency, amount_in_minor_units, fx_rate, supported)
        tuple for the display block of a quote.

        For INR: display equals the INR final (includes GST), fx_rate=1.
        For non-INR: GST is dropped (international customers don't pay
        Indian GST). amount = round(subtotal_paise / fx_rate).
        For unsupported currency: silently falls back to INR final with
        supported=False so the UI can refuse checkout in that currency.
        """
        target = (target_currency or "INR").strip().upper()
        supported = cls._supported_currencies()
        rates = cls._fx_rates()
        if target == "INR":
            return ("INR", final_inr_paise, 1.0, True)
        if target not in supported or target not in rates:
            # Fall back to INR but flag for the caller.
            return ("INR", final_inr_paise, 1.0, False)
        fx = rates[target]
        # GST is INR-only; international customers don't pay it. So we
        # convert from the pre-GST INR subtotal (NOT the post-GST final).
        # Round to nearest minor unit. round() ties-to-even is fine here
        # — at our price points a single-paisa drift is below the noise
        # floor of FX volatility.
        amount = int(round(subtotal_paise / fx))
        return (target, amount, fx, True)

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
        display_currency, display_amount_minor, fx_rate, supported = \
            cls._build_display_block(target_currency, subtotal, final_price)
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
            display_currency=display_currency,
            display_amount_minor=display_amount_minor,
            display_fx_rate=fx_rate,
            display_currency_supported=supported,
        )
