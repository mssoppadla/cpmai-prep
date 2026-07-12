"""Idempotent state transitions for a `Payment` row.

Two paths can advance a payment to its final state and they MUST agree:

  • the synchronous /payments/verify call (in-browser flow), and
  • the Razorpay webhook (out-of-band, fires regardless of whether the
    user kept the tab open).

Both call the functions in this module. Each function:

  • Is safe to re-run on an already-settled Payment (no double-counting,
    no duplicate Subscription row, no duplicate OfferRedemption).
  • Commits its own transaction so the caller doesn't have to track
    state across the boundary.

Why a separate module:
  - The verify endpoint and the webhook endpoint MUST not drift. Putting
    the activation logic here removes the temptation to bug-fix one
    without the other.
  - Tests can call these functions directly without going through HTTP.

Failure mode if both fire (race): the second call is a no-op because we
check `payment.status == "captured" and subscription_id is set` first.
A short window where verify writes Subscription before webhook arrives
is normal and expected — webhook just observes the existing state.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.exceptions import AppError
from app.models.offer import OfferCode, OfferRedemption
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.services.tracking_service import emit_event


def activate_subscription_for_payment(db: Session, payment: Payment) -> Subscription:
    """Mark `payment` as captured and ensure the user has an active sub.

    Idempotent: if a sub already exists for this payment, returns it
    unchanged. Records the OfferRedemption row on first activation only.
    Commits before returning.

    Raises AppError(500) if the plan was deleted between order create
    and activation — at that point the payment can't be honoured and
    needs admin intervention (refund manually).
    """
    if payment.plan_id is None:
        raise AppError("Payment is missing a plan_id.", status_code=500)

    # Already settled — nothing to do.
    if payment.status == "captured" and payment.subscription_id:
        existing = db.get(Subscription, payment.subscription_id)
        if existing is not None:
            return existing

    plan = db.get(Plan, payment.plan_id)
    if plan is None:
        raise AppError("Plan no longer exists.", status_code=500)

    payment.status = "captured"
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=plan.duration_days)

    # Extend an active subscription for the same user+plan, otherwise
    # create one. Renewing a still-active sub adds the full plan
    # duration on top of the current expiry instead of overlapping.
    sub = (db.query(Subscription)
           .filter_by(user_id=payment.user_id, plan_id=plan.id,
                       status="active")
           .first())
    if sub:
        anchor = (sub.expires_at if (sub.expires_at and sub.expires_at > now)
                  else now)
        sub.expires_at = anchor + timedelta(days=plan.duration_days)
        sub.current_period_end = sub.expires_at
    else:
        sub = Subscription(
            user_id=payment.user_id, plan=plan.slug, plan_id=plan.id,
            status="active",
            current_period_start=now, current_period_end=expires_at,
            expires_at=expires_at,
        )
        db.add(sub); db.flush()
    payment.subscription_id = sub.id

    # Append-only redemption ledger. Skip if an entry exists (idempotent
    # under both verify-then-webhook and webhook-then-verify orderings).
    if payment.offer_code:
        applied = (db.query(OfferCode)
                   .filter_by(code=payment.offer_code).first())
        if applied:
            already = (db.query(OfferRedemption)
                       .filter_by(offer_code_id=applied.id,
                                   payment_id=payment.id).first())
            if not already:
                db.add(OfferRedemption(
                    offer_code_id=applied.id, user_id=payment.user_id,
                    plan_id=plan.id, payment_id=payment.id,
                    discount_paise=payment.discount_paise or 0,
                ))

    db.commit()
    emit_event(db, "payment.success", user_id=payment.user_id,
               metadata={"plan_slug": plan.slug,
                         "amount_paise": payment.amount_paise,
                         "offer_code": payment.offer_code,
                         "provider_name": payment.provider_name,
                         "provider_order_id": payment.provider_order_id})
    audit_log(db, payment.user_id, "payment.success",
              {"plan_slug": plan.slug,
               "provider_name": payment.provider_name,
               "order_id": payment.provider_order_id,
               "amount_paise": payment.amount_paise})

    # Lifecycle email automations (fail-soft, idempotent under the
    # verify-vs-webhook race via the outbox dedup key). Also cancel any
    # queued "you haven't paid yet" nudges — they no longer apply.
    from app.models.user import User
    from app.services.email.automation import (
        cancel_unpaid_nudges, enqueue_for_trigger,
    )
    user = db.get(User, payment.user_id)
    if user is not None:
        enqueue_for_trigger(
            db, "payment.success", user,
            event_ref=f"pay{payment.id}",
            context_extra={
                "plan_name": plan.name,
                "amount": f"{(payment.amount_paise or 0) / 100:.2f}",
                "currency": payment.currency,
                "expires_at": (sub.expires_at.strftime("%d %b %Y")
                               if sub.expires_at else ""),
            })
    cancel_unpaid_nudges(db, payment.user_id)
    return sub



def _release_offer_seat(db: Session, payment: Payment) -> None:
    """Return a reserved offer-code seat to the pool — shared by the
    failed and cancelled paths. Only releases if no redemption row
    exists for this payment (a redemption row means the seat was
    already claimed successfully)."""
    if not payment.offer_code:
        return
    offer = (db.query(OfferCode)
             .filter_by(code=payment.offer_code).first())
    if offer is not None and (offer.used_count or 0) > 0:
        redeemed = (db.query(OfferRedemption)
                    .filter_by(offer_code_id=offer.id,
                                payment_id=payment.id)
                    .first())
        if redeemed is None:
            offer.used_count -= 1


def mark_payment_cancelled(db: Session, payment: Payment) -> None:
    """Record a checkout the buyer abandoned on the gateway's hosted
    page (clicked cancel OR hit the gateway's own error — e.g. PayPal's
    guest-card form failing for ineligible buyers).

    Distinct from mark_payment_failed: 'failed' means the gateway
    DECLINED a capture we attempted; 'cancelled' means no payment was
    ever attempted on our rails. No "payment failed" email nudge here —
    but the journey event makes the drop-off visible in Visitor
    Insights and the admin payments list instead of leaving the row in
    'created' forever.

    Idempotent, and deliberately touches ONLY rows still in 'created' —
    a late cancel-report must never downgrade a captured/failed row.
    """
    if payment.status != "created":
        return
    payment.status = "cancelled"
    _release_offer_seat(db, payment)
    db.commit()
    emit_event(db, "payment.checkout_cancelled", user_id=payment.user_id,
               metadata={"provider_name": payment.provider_name,
                          "provider_order_id": payment.provider_order_id,
                          "plan_id": payment.plan_id})

def mark_payment_failed(db: Session, payment: Payment) -> None:
    """Flip `payment` to status='failed' and release any reserved
    offer-code seat.

    Idempotent: re-runs after the first call are no-ops. Commits before
    returning. Releasing the offer seat is best-effort; if the row was
    already counted toward a different captured sale (impossible with
    the unique-on-payment_id constraint, but coded defensively), the
    decrement is skipped.
    """
    if payment.status == "failed":
        return

    payment.status = "failed"
    _release_offer_seat(db, payment)
    db.commit()
    emit_event(db, "payment.failed", user_id=payment.user_id,
               metadata={"provider_name": payment.provider_name,
                          "provider_order_id": payment.provider_order_id})

    # Lifecycle email automations (fail-soft) — the "payment failed,
    # need help?" nudge, deduped per payment id.
    from app.models.user import User
    from app.services.email.automation import enqueue_for_trigger
    user = db.get(User, payment.user_id)
    if user is not None:
        plan = db.get(Plan, payment.plan_id) if payment.plan_id else None
        enqueue_for_trigger(
            db, "payment.failed", user,
            event_ref=f"pay{payment.id}",
            context_extra={
                "plan_name": plan.name if plan else "",
                "amount": f"{(payment.amount_paise or 0) / 100:.2f}",
                "currency": payment.currency,
                "provider": payment.provider_name,
            })


def find_payment_for_event(db: Session, event: dict) -> Payment | None:
    """Pull the Payment row a Razorpay webhook event refers to.

    Razorpay nests the order_id under different paths depending on the
    event type:
      payment.captured / payment.failed → payload.payment.entity.order_id
      order.paid                        → payload.order.entity.id
    Returns None if the event doesn't reference a known order — the
    webhook handler still persists the row to WebhookEvent for audit.

    PayPal-shaped events use a different shape and are dispatched by
    ``find_payment_for_paypal_event`` instead; this function is the
    Razorpay-specific path called from /payments/webhook.
    """
    payload = event.get("payload", {}) or {}
    rzp_order_id = (
        payload.get("payment", {}).get("entity", {}).get("order_id")
        or payload.get("order", {}).get("entity", {}).get("id")
    )
    if not rzp_order_id:
        return None
    return (db.query(Payment)
            .filter_by(provider_order_id=rzp_order_id,
                        provider_name="razorpay").first())


def find_payment_for_paypal_event(db: Session, event: dict) -> Payment | None:
    """Pull the Payment row a PayPal webhook event refers to.

    PayPal's Orders v2 events put the order_id in different places:

      * PAYMENT.CAPTURE.* events nest it under
        ``resource.supplementary_data.related_ids.order_id`` (the
        capture is on the order, and PayPal includes the parent
        order_id in the related_ids block).
      * Some payloads also include a ``custom_id`` on the resource
        that equals our internal idempotency key — a fallback path
        if related_ids is missing.

    Returns None if neither lookup finds a matching Payment row. The
    webhook handler still records the WebhookEvent for audit so an
    operator can investigate the orphan event.
    """
    res = (event.get("resource") or {})
    # Primary path — most PAYMENT.CAPTURE.* events carry the parent
    # order_id under supplementary_data.related_ids.
    paypal_order_id = (((res.get("supplementary_data") or {})
                        .get("related_ids") or {})
                       .get("order_id"))
    # Fallback — CHECKOUT.ORDER.* events put the order_id directly on
    # resource.id (the resource IS the order, not a capture). We were
    # tempted to fold this into a single expression with `or` + ternary,
    # but Python's precedence makes that buggy. Two lines, no surprise.
    if not paypal_order_id and (event.get("event_type") or "").startswith(
            "CHECKOUT.ORDER."):
        paypal_order_id = res.get("id")
    if paypal_order_id:
        match = (db.query(Payment)
                 .filter_by(provider_order_id=paypal_order_id,
                            provider_name="paypal").first())
        if match:
            return match
    # Fallback: custom_id lookup against our idempotency_key — useful
    # when an event arrives with a degraded payload.
    custom_id = res.get("custom_id")
    if custom_id:
        return (db.query(Payment)
                .filter_by(idempotency_key=custom_id,
                            provider_name="paypal").first())
    return None
