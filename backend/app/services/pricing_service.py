"""Server-side price computation engine.

Single source of truth for "what does a Plan + OfferCode cost?". Every
endpoint that computes a price (public quote, order create, admin
preview) goes through here so frontend and backend never disagree.

Returned `PriceQuote` is intentionally a plain dataclass — easy to
serialise to JSON, easy to assert on in tests, never holds session.

Stacking semantics (governed by `pricing.stack_offer_with_discount`):

  • Off (default):
      - If plan has a `discount_price`, that wins. Offer code is silently
        ignored, `applied=false` returned in the breakdown so UI can
        show "your discount is already better than this code".
      - If plan has NO `discount_price`, the offer applies to base_price.
  • On:
      - Effective price starts at `discount_price` if present else
        `base_price`. The offer code is then applied on top.

Final price is clamped to >= 0 in both modes.
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

    # Final price the user pays
    final_price_paise: int

    # The combine-toggle that was in effect at quote time. Stored on
    # Payment so audits can prove which mode produced the charge.
    stack_offer_with_discount: bool

    def to_dict(self) -> dict:
        return asdict(self)


class PricingService:
    """Stateless on the surface — takes a session for OfferCode lookups
    only. All numeric work is pure."""

    def __init__(self, db: Session):
        self.db = db

    # --------------------------------------------------------- public API
    def quote(self, plan_slug: str,
              offer_code: Optional[str] = None) -> PriceQuote:
        """Compute the price the user would pay right now for plan_slug.

        Raises NotFoundError if the plan doesn't exist or is inactive.
        Returns a quote even when the offer is invalid/expired — the
        breakdown explains why and `final_price_paise` matches the
        no-offer case. Frontend can render that as a soft warning rather
        than an error.
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
                final_price=effective_before_offer,
                stack=stack,
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
                final_price=effective_before_offer,
                stack=stack,
            )

        ineligibility = self._eligibility_reason(code, plan)
        if ineligibility:
            return self._build_quote(
                plan=plan,
                effective_before_offer=effective_before_offer,
                offer_code=normalised_code, offer_applied=False,
                offer_reason=ineligibility,
                offer_discount=0,
                final_price=effective_before_offer,
                stack=stack,
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
                final_price=effective_before_offer,
                stack=stack,
            )

        # Apply the offer.
        target = (effective_before_offer if stack
                  else plan.base_price_paise)
        discount = self._compute_discount_paise(code, target)
        final = max(0, effective_before_offer - discount) if stack \
                else max(0, plan.base_price_paise - discount)

        return self._build_quote(
            plan=plan,
            effective_before_offer=effective_before_offer,
            offer_code=code.code, offer_applied=True, offer_reason=None,
            offer_discount=discount,
            final_price=final,
            stack=stack,
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
    def _build_quote(*, plan: Plan, effective_before_offer: int,
                     offer_code, offer_applied, offer_reason,
                     offer_discount, final_price, stack) -> PriceQuote:
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
            final_price_paise=final_price,
            stack_offer_with_discount=stack,
        )
