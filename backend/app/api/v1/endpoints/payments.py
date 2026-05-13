"""Payment endpoints — plan-driven (server is the only price authority).

Lifecycle:
  1. POST /payments/orders {plan_slug, offer_code?, referrer?}
     → server computes price via PricingService, creates Razorpay order,
       persists Payment(plan_id, base, discount, offer_code, referrer).
  2. POST /payments/verify {order_id, payment_id, signature}
     → fast-path for the in-browser flow. Verify signature, then call
       activate_subscription_for_payment() so the user lands on /exams
       with access immediately.
  3. POST /payments/webhook  → authoritative out-of-band callback from
       Razorpay. Handles dropped tabs, network blips, anything that
       prevents step 2 from firing. Routes by event type to the SAME
       activation function as verify (idempotent).

Verify and webhook share `app.services.payment_lifecycle` so they can't
drift. If both fire (the common case), the second call is a no-op
because activate_subscription_for_payment short-circuits when the
subscription_id is already set.
"""
import json
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_current_user
from app.core.exceptions import AppError, NotFoundError
from app.core.limiter import limiter
from app.models.user import User
from app.models.payment import Payment, WebhookEvent
from app.models.offer import OfferCode
from app.schemas.payment import (
    CreateOrderIn, CreateOrderOut, VerifyPaymentIn, VerifyPaymentOut,
)
from app.services.payment_registry import PaymentRegistry
from app.services.payment_lifecycle import (
    activate_subscription_for_payment, mark_payment_failed,
    find_payment_for_event,
)
from app.services.pricing_service import PricingService
from app.services.tracking_service import emit_event

router = APIRouter()


@router.post("/orders", response_model=CreateOrderOut, status_code=201)
def create_order(payload: CreateOrderIn,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    pricing = PricingService(db)
    requested_currency = (payload.currency or "INR").upper()
    quote = pricing.quote(payload.plan_slug, payload.offer_code,
                          currency=requested_currency)

    # If the caller asked for a currency we can't charge in, REJECT
    # rather than silently downgrading to INR. /pricing/quote falls
    # back to INR for the display block, but here we're about to
    # actually charge — they'd be very upset if they thought they
    # were paying $X and we charged ₹X*83.
    if not quote.display_currency_supported:
        raise AppError(
            f"Currency '{requested_currency}' is not supported for payment. "
            "Refresh the pricing page and pick from the available list.",
            status_code=400)

    if quote.final_price_paise <= 0:
        # 100% off: no Razorpay round-trip needed. Caller can short-
        # circuit straight to a free subscription if they want; for
        # now we keep it simple and reject so the front-end never
        # tries to verify a non-existent payment.
        raise AppError(
            "This combination would result in a free order. "
            "Activate the plan via the admin console instead.",
            status_code=400)

    # Charge currency + minor-unit amount that Razorpay will see.
    # For INR this is unchanged (paise, "INR"). For non-INR this is
    # the FX-converted amount in the target currency's minor units
    # AND we explicitly drop GST (international customers don't pay
    # Indian GST).
    charge_currency = quote.display_currency
    charge_amount_minor = quote.display_amount_minor

    if charge_amount_minor <= 0:
        # Defensive — shouldn't happen given the final_price_paise check
        # above, but FX rounding on tiny prices could theoretically zero
        # out the converted amount.
        raise AppError(
            f"Converted amount for {charge_currency} is zero. "
            "Check the FX rate in /admin/settings (pricing.fx_rates_inr_per_unit).",
            status_code=400)

    provider = PaymentRegistry.get_active()
    # Receipt doubles as our idempotency_key (unique on payments). Add
    # an 8-byte random suffix so two orders in the same second can't
    # collide. Razorpay caps receipts at ~40 chars; this stays under.
    receipt = (f"u_{user.id}_p_{quote.plan_id}_"
               f"{int(datetime.now().timestamp())}_"
               f"{secrets.token_hex(4)}")
    # Wrap any gateway error in a clean AppError so CORS headers + JSON
    # body are preserved. Razorpay's SDK raises subclasses of Exception
    # for auth failures, network errors, validation issues — none of
    # which our caller can act on except by re-entering credentials.
    try:
        order = provider.create_order(
            charge_amount_minor, receipt=receipt,
            currency=charge_currency)
    except Exception as e:
        raise AppError(
            f"Payment gateway rejected the order: {e}. "
            "Verify the active provider's keys in admin → Payment Providers. "
            "If you're using a non-INR currency, also check that the Razorpay "
            "account has international payments enabled.",
            status_code=502)

    # Reserve a redemption seat NOW so concurrent buyers can't both grab
    # the last copy of a code with max_redemptions=1. The webhook handler
    # releases the seat on payment.failed (see payment_lifecycle.py).
    if quote.offer_applied:
        applied = (db.query(OfferCode)
                   .filter_by(code=quote.offer_code).first())
        if applied:
            if not pricing.reserve_offer_redemption(applied.id):
                raise AppError(
                    "Offer code is no longer available.", status_code=409)

    # discount_paise on Payment captures everything knocked off the
    # base — both plan-level discount_price AND offer-code reductions.
    # GST is NOT a discount, so it's not subtracted here. Compare base
    # against the post-offer SUBTOTAL (pre-GST), not final_price_paise
    # (which now includes GST).
    discount = quote.base_price_paise - quote.subtotal_paise
    # amount_paise on the Payment row stores what we ACTUALLY charge
    # (in the charge currency's minor units, not always paise — the
    # column name is historic, kept for compatibility). The currency
    # column distinguishes INR from non-INR.
    db.add(Payment(
        user_id=user.id, plan_id=quote.plan_id,
        razorpay_order_id=order["id"],
        amount_paise=charge_amount_minor,
        base_amount_paise=quote.base_price_paise,
        discount_paise=max(0, discount),
        offer_code=quote.offer_code if quote.offer_applied else None,
        referrer=payload.referrer,
        currency=charge_currency, status="created",
        idempotency_key=receipt,
    ))
    db.commit()
    emit_event(db, "payment.order_created", user_id=user.id,
               metadata={"order_id": order["id"], "plan_slug": quote.plan_slug,
                          "offer_code": quote.offer_code,
                          "currency": charge_currency,
                          "amount_minor": charge_amount_minor,
                          "amount_inr_paise": quote.final_price_paise,
                          "gst_paise": quote.gst_paise,
                          "fx_rate": quote.display_fx_rate})

    return CreateOrderOut(
        order_id=order["id"],
        amount=order["amount"], currency=order["currency"],
        razorpay_key_id=provider.key_id,
        plan_slug=quote.plan_slug, plan_name=quote.plan_name,
        base_amount=quote.base_price_paise,
        discount_amount=max(0, discount),
        subtotal_amount=quote.subtotal_paise,
        gst_percent=quote.gst_percent if charge_currency == "INR" else 0,
        gst_amount=quote.gst_paise if charge_currency == "INR" else 0,
        offer_code=quote.offer_code,
        offer_applied=quote.offer_applied,
        offer_reason=quote.offer_reason,
        final_inr_paise=quote.final_price_paise,
        fx_rate=float(quote.display_fx_rate or 1.0),
    )


@router.post("/verify", response_model=VerifyPaymentOut)
def verify_payment(payload: VerifyPaymentIn,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Fast-path activation for the in-browser flow.

    Verifies the HMAC signature Razorpay gave the popup, then delegates
    to the same activation function the webhook uses. Re-running this
    after the webhook already activated is a no-op.
    """
    provider = PaymentRegistry.get_active()
    if not provider.verify_payment_signature(
        payload.order_id, payload.payment_id, payload.signature):
        raise AppError("Invalid payment signature.", status_code=400)

    payment = db.query(Payment).filter_by(
        razorpay_order_id=payload.order_id, user_id=user.id).first()
    if not payment:
        raise NotFoundError("Order not found.")

    # Persist the razorpay_payment_id ASAP — webhook may not include it
    # under the same path, and analytics queries join on it.
    if not payment.razorpay_payment_id:
        payment.razorpay_payment_id = payload.payment_id
        db.flush()

    sub = activate_subscription_for_payment(db, payment)
    return VerifyPaymentOut(
        status="active", plan_slug=sub.plan, expires_at=sub.expires_at,
    )


@router.post("/webhook")
@limiter.limit("100/minute")
async def webhook(request: Request,
                  x_razorpay_signature: str = Header(default=""),
                  db: Session = Depends(get_db)):
    """Razorpay-side authoritative settlement.

    Fires regardless of whether the user kept the browser tab open. Same
    activation path as /verify, so dropped-tab purchases still grant
    access. Idempotent on event_id (we dedupe via WebhookEvent) AND on
    state (activate function short-circuits on already-active).

    Event types handled:
      payment.captured → activate subscription
      order.paid       → activate subscription (alias)
      payment.failed   → mark Payment failed, release offer-code seat
      *                → log only (audit trail, no state change)
    """
    body = await request.body()
    provider = PaymentRegistry.get_active()
    if not provider.verify_webhook_signature(body, x_razorpay_signature):
        raise AppError("Invalid webhook signature.", status_code=400)

    event = json.loads(body)
    event_id = (event.get("id")
                or event.get("payload", {})
                       .get("payment", {})
                       .get("entity", {})
                       .get("id"))
    if not event_id:
        raise AppError("Missing event id", status_code=400)

    if db.query(WebhookEvent).filter_by(event_id=event_id).first():
        return {"received": True, "duplicate": True}

    event_type = event.get("event") or ""
    payment = find_payment_for_event(db, event)
    action = "ignored"

    if payment is not None:
        # Capture razorpay_payment_id from the webhook payload too —
        # belt-and-braces, in case verify never fired.
        rzp_pid = (event.get("payload", {})
                   .get("payment", {})
                   .get("entity", {}).get("id"))
        if rzp_pid and not payment.razorpay_payment_id:
            payment.razorpay_payment_id = rzp_pid
            db.flush()

        if event_type in ("payment.captured", "order.paid"):
            activate_subscription_for_payment(db, payment)
            action = "activated"
        elif event_type == "payment.failed":
            mark_payment_failed(db, payment)
            action = "failed"

    db.add(WebhookEvent(event_id=event_id, payload=event,
                        processed_at=datetime.now(timezone.utc)))
    db.commit()
    return {"received": True, "event_type": event_type, "action": action}
