"""Payment endpoints — plan-driven (server is the only price authority).

Flow:
  1. POST /payments/orders {plan_slug, offer_code?, referrer?}
     → server computes price via PricingService, creates Razorpay order,
       persists Payment(plan_id, base, discount, offer_code, referrer).
  2. POST /payments/verify {order_id, payment_id, signature}
     → verify HMAC; flip Payment.status='captured';
       create/extend Subscription(plan_id, expires_at = paid_at + plan.duration_days);
       record OfferRedemption row if an offer was used.
  3. POST /payments/webhook  → idempotent dedupe (hardening in phase 3).
"""
import json
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_current_user
from app.core.exceptions import AppError, NotFoundError
from app.core.audit import audit_log
from app.core.limiter import limiter
from app.models.user import User
from app.models.payment import Payment, WebhookEvent
from app.models.subscription import Subscription
from app.models.plan import Plan
from app.models.offer import OfferCode, OfferRedemption
from app.schemas.payment import (
    CreateOrderIn, CreateOrderOut, VerifyPaymentIn, VerifyPaymentOut,
)
from app.services.payment_registry import PaymentRegistry
from app.services.pricing_service import PricingService
from app.services.tracking_service import emit_event

router = APIRouter()


@router.post("/orders", response_model=CreateOrderOut, status_code=201)
def create_order(payload: CreateOrderIn,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    pricing = PricingService(db)
    quote = pricing.quote(payload.plan_slug, payload.offer_code)

    if quote.final_price_paise <= 0:
        # 100% off: no Razorpay round-trip needed. Caller can short-
        # circuit straight to a free subscription if they want; for
        # now we keep it simple and reject so the front-end never
        # tries to verify a non-existent payment.
        raise AppError(
            "This combination would result in a free order. "
            "Activate the plan via the admin console instead.",
            status_code=400)

    provider = PaymentRegistry.get_active()
    # Receipt doubles as our idempotency_key (unique on payments). Add
    # an 8-byte random suffix so two orders in the same second can't
    # collide. Razorpay caps receipts at ~40 chars; this stays under.
    receipt = (f"u_{user.id}_p_{quote.plan_id}_"
               f"{int(datetime.now().timestamp())}_"
               f"{secrets.token_hex(4)}")
    order = provider.create_order(quote.final_price_paise, receipt=receipt,
                                   currency=quote.currency)

    # Reserve a redemption seat NOW so concurrent buyers can't both grab
    # the last copy of a code with max_redemptions=1. Released if the
    # user never completes verify (manual cleanup; webhook hardening
    # phase will do this automatically on payment.failed).
    offer_code_id_for_release = None
    if quote.offer_applied:
        applied = (db.query(OfferCode)
                   .filter_by(code=quote.offer_code).first())
        if applied:
            if not pricing.reserve_offer_redemption(applied.id):
                raise AppError(
                    "Offer code is no longer available.", status_code=409)
            offer_code_id_for_release = applied.id

    discount = quote.effective_before_offer_paise - quote.final_price_paise \
               if quote.offer_applied \
               else (quote.base_price_paise - quote.final_price_paise)
    db.add(Payment(
        user_id=user.id, plan_id=quote.plan_id,
        razorpay_order_id=order["id"],
        amount_paise=quote.final_price_paise,
        base_amount_paise=quote.base_price_paise,
        discount_paise=max(0, discount),
        offer_code=quote.offer_code if quote.offer_applied else None,
        referrer=payload.referrer,
        currency=quote.currency, status="created",
        idempotency_key=receipt,
    ))
    db.commit()
    emit_event(db, "payment.order_created", user_id=user.id,
               metadata={"order_id": order["id"], "plan_slug": quote.plan_slug,
                          "offer_code": quote.offer_code,
                          "amount_paise": quote.final_price_paise})

    return CreateOrderOut(
        order_id=order["id"],
        amount=order["amount"], currency=order["currency"],
        razorpay_key_id=provider.key_id,
        plan_slug=quote.plan_slug, plan_name=quote.plan_name,
        base_amount=quote.base_price_paise,
        discount_amount=max(0, discount),
        offer_code=quote.offer_code,
        offer_applied=quote.offer_applied,
        offer_reason=quote.offer_reason,
    )


@router.post("/verify", response_model=VerifyPaymentOut)
def verify_payment(payload: VerifyPaymentIn,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    provider = PaymentRegistry.get_active()
    if not provider.verify_payment_signature(
        payload.order_id, payload.payment_id, payload.signature):
        raise AppError("Invalid payment signature.", status_code=400)

    payment = db.query(Payment).filter_by(
        razorpay_order_id=payload.order_id, user_id=user.id).first()
    if not payment:
        raise NotFoundError("Order not found.")
    if payment.plan_id is None:
        raise AppError("Payment is missing a plan_id.", status_code=500)

    plan = db.get(Plan, payment.plan_id)
    if plan is None:
        raise AppError("Plan no longer exists.", status_code=500)

    payment.razorpay_payment_id = payload.payment_id
    payment.status = "captured"

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=plan.duration_days)

    # Extend an active subscription if one already exists for this plan
    # (e.g. user buys early-renewal). Otherwise create a fresh row.
    sub = (db.query(Subscription)
           .filter_by(user_id=user.id, plan_id=plan.id, status="active")
           .first())
    if sub:
        # Take the later of (current expiry, now) and add the plan
        # duration on top — so renewing a still-active sub adds full
        # duration rather than overlapping.
        anchor = sub.expires_at if (sub.expires_at and sub.expires_at > now) else now
        sub.expires_at = anchor + timedelta(days=plan.duration_days)
        sub.current_period_end = sub.expires_at
    else:
        sub = Subscription(
            user_id=user.id, plan=plan.slug, plan_id=plan.id,
            status="active",
            current_period_start=now, current_period_end=expires_at,
            expires_at=expires_at,
        )
        db.add(sub); db.flush()
    payment.subscription_id = sub.id

    # Persist the redemption (if any) — append-only audit row.
    if payment.offer_code:
        applied = (db.query(OfferCode)
                   .filter_by(code=payment.offer_code).first())
        if applied:
            already = (db.query(OfferRedemption)
                       .filter_by(offer_code_id=applied.id,
                                   payment_id=payment.id).first())
            if not already:
                db.add(OfferRedemption(
                    offer_code_id=applied.id, user_id=user.id,
                    plan_id=plan.id, payment_id=payment.id,
                    discount_paise=payment.discount_paise or 0,
                ))

    db.commit()
    emit_event(db, "payment.success", user_id=user.id,
               metadata={"plan_slug": plan.slug,
                         "amount_paise": payment.amount_paise,
                         "offer_code": payment.offer_code})
    audit_log(db, user.id, "payment.success",
              {"plan_slug": plan.slug, "order_id": payload.order_id,
               "amount_paise": payment.amount_paise})
    return VerifyPaymentOut(
        status="active", plan_slug=plan.slug, expires_at=sub.expires_at,
    )


@router.post("/webhook")
@limiter.limit("100/minute")
async def webhook(request: Request,
                  x_razorpay_signature: str = Header(default=""),
                  db: Session = Depends(get_db)):
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

    db.add(WebhookEvent(event_id=event_id, payload=event,
                        processed_at=datetime.now(timezone.utc)))
    db.commit()
    return {"received": True}
