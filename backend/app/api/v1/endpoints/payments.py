"""Payment endpoints — plan-driven (server is the only price authority).

Two rails coexist (currency-routed at order-create time):

  * **INR rail — Razorpay.** Existing flow. Order create → Razorpay
    Checkout popup → /payments/verify (HMAC signature) and/or
    /payments/webhook (HMAC signature). All payment IDs follow
    Razorpay's shape; provider_name="razorpay" on the Payment row.

  * **Non-INR rail — PayPal.** New flow.
      1. /payments/orders with currency != INR routes to the PayPal
         provider. We call PayPal's Orders v2 create, persist a Payment
         row with provider_name="paypal" + the PayPal order id, return
         {provider:"paypal", paypal_client_id, paypal_approval_url}.
      2. Frontend renders PayPal Smart Button using paypal_client_id;
         buyer approves on PayPal's domain.
      3. Smart Button's onApprove callback hits /payments/paypal/capture
         which calls PayPal's capture API. Subscription activates on
         capture success.
      4. /payments/paypal/webhook handles dropped-browser-tab cases —
         same activation function via the lifecycle module.

Verify (Razorpay), capture (PayPal), and both webhooks share
``app.services.payment_lifecycle`` so they can't drift. If multiple
paths fire (the common case for fast in-browser flows), the second
call is a no-op because activate_subscription_for_payment short-
circuits when the subscription_id is already set.
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
from app.models.lead import Lead, LeadSource
from app.schemas.payment import (
    CreateOrderIn, CreateOrderOut, VerifyPaymentIn, VerifyPaymentOut,
    PayPalCancelledIn, PayPalCancelledOut, PayPalCaptureIn, PayPalCaptureOut,
)
from app.services.payment_registry import PaymentRegistry
from app.services.payment_lifecycle import (
    activate_subscription_for_payment, mark_payment_cancelled, mark_payment_failed,
    find_payment_for_event, find_payment_for_paypal_event,
)
from app.services.pricing_service import PricingService
from app.services.tracking_service import emit_event

router = APIRouter()


def _capture_linkedin_lead(db: Session, email: str | None, linkedin_id: str | None) -> None:
    """Capture the LinkedIn id an aspirant left at checkout by upserting a lead keyed by their
    email — so admins already see it on the Users/Contacts screens. Never blocks the order."""
    linkedin_id = (linkedin_id or "").strip()[:255]
    if not linkedin_id or not email:
        return
    lead = (db.query(Lead).filter(Lead.email == email.lower())
            .order_by(Lead.created_at.desc()).first())
    if lead is None:
        db.add(Lead(email=email.lower(), source=LeadSource.PRICING_PAGE, linkedin_id=linkedin_id))
    elif not lead.linkedin_id:
        lead.linkedin_id = linkedin_id


@router.post("/orders", response_model=CreateOrderOut, status_code=201)
def create_order(payload: CreateOrderIn,
                 request: Request,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    _capture_linkedin_lead(db, user.email, payload.linkedin_id)
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

    # Currency drives provider selection: INR → Razorpay (existing
    # active provider); non-INR → PayPal (the configured non-INR
    # provider). Both flows persist a Payment row with provider_name
    # set so verify/capture/webhook can dispatch correctly.
    provider = PaymentRegistry.get_for_currency(charge_currency)

    # Receipt doubles as our idempotency_key (unique on payments). Add
    # an 8-byte random suffix so two orders in the same second can't
    # collide. Razorpay caps receipts at ~40 chars; PayPal's custom_id
    # accepts up to 127 — staying under Razorpay's cap covers both.
    receipt = (f"u_{user.id}_p_{quote.plan_id}_"
               f"{int(datetime.now().timestamp())}_"
               f"{secrets.token_hex(4)}")
    # Wrap any gateway error in a clean AppError so CORS headers + JSON
    # body are preserved. Razorpay's SDK and PayPal's REST client both
    # raise subclasses of Exception for auth failures, network errors,
    # validation issues — none of which our caller can act on except
    # by re-entering credentials.
    # PayPal needs return/cancel URLs so the buyer lands back on our
    # frontend after approving (or cancelling) on PayPal's domain. We
    # derive the frontend origin from the request's Origin header — set
    # by the browser on cross-origin POSTs from /pricing. Razorpay's
    # popup flow doesn't redirect away from the page, so the URLs are
    # PayPal-only.
    paypal_kwargs = {}
    if provider.name == "paypal":
        origin = request.headers.get("origin") or ""
        if not origin:
            raise AppError(
                "PayPal orders require the browser's Origin header to "
                "build the return URL. This usually means the request "
                "didn't come from a browser context — check the call "
                "site or supply a public_base_url setting.",
                status_code=400)
        paypal_kwargs = {
            "return_url": f"{origin}/payments/paypal/return",
            "cancel_url": f"{origin}/pricing?cancelled=1",
        }
    try:
        order = provider.create_order(
            charge_amount_minor, receipt=receipt,
            currency=charge_currency, **paypal_kwargs)
    except Exception as e:
        gateway_label = "Razorpay" if provider.name == "razorpay" else "PayPal"
        raise AppError(
            f"Payment gateway rejected the order: {e}. "
            f"Verify the {gateway_label} provider's keys in "
            f"admin → Payment Providers. "
            + ("If you're using a non-INR currency, also check that the "
                "Razorpay account has international payments enabled. "
               if provider.name == "razorpay" else
               "Confirm your PayPal Business account supports the requested "
                "currency on the merchant dashboard. "),
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
        provider_name=provider.name,
        provider_order_id=order["id"],
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
                          "fx_rate": quote.display_fx_rate,
                          "provider": provider.name})

    return CreateOrderOut(
        order_id=order["id"],
        amount=order["amount"], currency=order["currency"],
        provider=provider.name,
        razorpay_key_id=(provider.key_id if provider.name == "razorpay"
                          else None),
        paypal_client_id=(provider.key_id if provider.name == "paypal"
                           else None),
        paypal_approval_url=(order.get("approval_url")
                              if provider.name == "paypal" else None),
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
    """Fast-path activation for the in-browser RAZORPAY flow.

    Verifies the HMAC signature Razorpay gave the popup, then delegates
    to the same activation function the webhook uses. Re-running this
    after the webhook already activated is a no-op.

    PayPal uses /payments/paypal/capture instead — different signature
    scheme, different 2-step flow.
    """
    # Order must be a Razorpay-rail order — verify is the Razorpay flow.
    # Mismatched provider returns 400 rather than silently failing
    # signature check.
    payment = db.query(Payment).filter_by(
        provider_order_id=payload.order_id, user_id=user.id).first()
    if not payment:
        raise NotFoundError("Order not found.")
    if payment.provider_name != "razorpay":
        raise AppError(
            f"Order {payload.order_id} is a {payment.provider_name} order; "
            f"use the {payment.provider_name} flow instead.",
            status_code=400)

    provider = PaymentRegistry.get_for_currency(payment.currency)
    if not provider.verify_payment_signature(
        payload.order_id, payload.payment_id, payload.signature):
        raise AppError("Invalid payment signature.", status_code=400)

    # Persist the payment id ASAP — webhook may not include it under
    # the same path, and analytics queries join on it.
    if not payment.provider_payment_id:
        payment.provider_payment_id = payload.payment_id
        db.flush()

    sub = activate_subscription_for_payment(db, payment)
    return VerifyPaymentOut(
        status="active", plan_slug=sub.plan, expires_at=sub.expires_at,
    )


@router.post("/paypal/capture", response_model=PayPalCaptureOut)
def paypal_capture(payload: PayPalCaptureIn,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Fast-path activation for the in-browser PAYPAL flow.

    Frontend Smart Button's ``onApprove`` callback hits this with the
    PayPal order id. We then call PayPal's capture API to actually move
    the money. On success → activate subscription, same code path as
    Razorpay verify. Idempotent (re-capturing returns the existing
    capture, then activation short-circuits).

    Status semantics:
        "active"   → capture succeeded and subscription is live
        "pending"  → PayPal accepted the capture but hasn't completed
                     it (rare; happens with PayPal's risk-review queue).
                     Webhook will activate when the capture completes.
    """
    payment = db.query(Payment).filter_by(
        provider_order_id=payload.order_id, user_id=user.id).first()
    if not payment:
        raise NotFoundError("Order not found.")
    if payment.provider_name != "paypal":
        raise AppError(
            f"Order {payload.order_id} is a {payment.provider_name} order; "
            f"use the {payment.provider_name} flow instead.",
            status_code=400)

    provider = PaymentRegistry.get_for_currency(payment.currency)
    try:
        cap = provider.capture_order(payload.order_id)
    except AppError:
        raise
    except Exception as e:
        raise AppError(
            f"PayPal capture failed: {e}", status_code=502)

    # Persist the capture id (PayPal's analogue of razorpay_payment_id).
    # Even on PENDING/DECLINED we record what we got back — useful for
    # support tickets if the user lands on "thanks" but the sub isn't live.
    if cap.get("capture_id") and not payment.provider_payment_id:
        payment.provider_payment_id = cap["capture_id"]
        db.flush()

    status = (cap.get("status") or "").upper()
    if status == "DECLINED":
        mark_payment_failed(db, payment)
        raise AppError("PayPal declined the capture.", status_code=400)
    if status != "COMPLETED":
        # PENDING — webhook will activate later.
        db.commit()
        return PayPalCaptureOut(
            status="pending", plan_slug=(
                payment.plan_id and
                # The plan_slug we want here is the one from the order,
                # which we don't have on the Payment row directly. The
                # frontend already knows it (it just made the order).
                # Defensive fallback: empty string — the response stays
                # parseable, frontend trusts its own context.
                ""),
        )

    sub = activate_subscription_for_payment(db, payment)
    return PayPalCaptureOut(
        status="active", plan_slug=sub.plan, expires_at=sub.expires_at,
    )


@router.post("/paypal/cancelled", response_model=PayPalCancelledOut)
def paypal_cancelled(payload: PayPalCancelledIn,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Record a PayPal checkout the buyer abandoned.

    PayPal appends ``?token=<order_id>`` to our cancel_url, so the
    pricing page knows exactly which order died — whether the buyer
    clicked cancel or hit PayPal's own error page (the UK guest-card
    incident, 2026-07-12). Without this, the Payment row sits in
    'created' forever and the drop-off is invisible to admins.

    Only the order's owner can report it, and only 'created' rows
    change — a stale cancel report can never downgrade a captured or
    failed payment (mark_payment_cancelled enforces both).
    """
    payment = db.query(Payment).filter_by(
        provider_order_id=payload.order_id, user_id=user.id).first()
    if not payment:
        raise NotFoundError("Order not found.")
    mark_payment_cancelled(db, payment)
    return PayPalCancelledOut(status=payment.status)


@router.post("/webhook")
@limiter.limit("100/minute")
async def webhook(request: Request,
                  x_razorpay_signature: str = Header(default=""),
                  db: Session = Depends(get_db)):
    """RAZORPAY-side authoritative settlement.

    Fires regardless of whether the user kept the browser tab open. Same
    activation path as /verify, so dropped-tab purchases still grant
    access. Idempotent on event_id (we dedupe via WebhookEvent) AND on
    state (activate function short-circuits on already-active).

    Event types handled:
      payment.captured → activate subscription
      order.paid       → activate subscription (alias)
      payment.failed   → mark Payment failed, release offer-code seat
      *                → log only (audit trail, no state change)

    PayPal goes through /payments/paypal/webhook — different signature
    scheme (certificate-based, not shared HMAC).
    """
    body = await request.body()
    # Razorpay's INR provider is always the "active" one in our setup.
    provider = PaymentRegistry.get_active()
    if not provider.verify_webhook_signature(body, x_razorpay_signature):
        # Operator-facing diagnostic. Razorpay auto-disables an endpoint
        # that keeps rejecting deliveries, and the usual cause is a
        # secret-mismatch between our /admin/payment-providers row and
        # the Razorpay dashboard. Log just enough context for the admin
        # to spot which side is stale, without leaking the secrets:
        #   * presence flag — was webhook_secret configured at all?
        #   * first-8 chars of the signature Razorpay sent — non-secret,
        #     used as a copy-paste correlation hint when comparing with
        #     the test-webhook-signature endpoint
        #   * body length + first 32 chars — enough to identify the event
        #     in Razorpay's dashboard "Recent deliveries" view
        from app.core.audit import audit_log
        body_preview = body[:64].decode("utf-8", errors="replace")
        audit_log(
            db, None, "razorpay.webhook_rejected_invalid_signature",
            {
                "received_sig_prefix": (x_razorpay_signature or "")[:8] or None,
                "body_length": len(body),
                "body_preview": body_preview,
                "secret_configured": bool(
                    getattr(provider, "_webhook_secret", None)),
            },
        )
        raise AppError(
            "Invalid webhook signature. Most likely the webhook secret "
            "in /admin/payment-providers doesn't match the one in the "
            "Razorpay dashboard. Open admin → Payment Providers → "
            "click 'Test Webhook Signature' on the Razorpay row to "
            "verify against a sample delivery.",
            status_code=400)

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
        # Capture the Razorpay payment id from the webhook payload too —
        # belt-and-braces, in case verify never fired.
        rzp_pid = (event.get("payload", {})
                   .get("payment", {})
                   .get("entity", {}).get("id"))
        if rzp_pid and not payment.provider_payment_id:
            payment.provider_payment_id = rzp_pid
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


@router.post("/paypal/webhook")
@limiter.limit("100/minute")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    """PAYPAL-side authoritative settlement.

    PayPal's webhook signing scheme is certificate-based, not HMAC. We
    forward the inbound headers + body to PayPal's
    verify-webhook-signature API; PayPal returns SUCCESS / FAILURE. The
    PayPalProvider does that round-trip in ``verify_webhook(...)``.

    Event types handled (PayPal Orders v2):
        PAYMENT.CAPTURE.COMPLETED → activate subscription
        PAYMENT.CAPTURE.DENIED    → mark Payment failed, release seat
        PAYMENT.CAPTURE.REFUNDED  → log only (refund flow is admin-side)
        *                         → log only (audit trail)

    Idempotency: PayPal events have a unique ``id`` field; we dedupe via
    the same WebhookEvent table as Razorpay so an out-of-order webhook
    re-delivery can't activate twice.
    """
    body = await request.body()
    # PayPal lives on the non-INR rail. Use the configured non-INR
    # provider regardless of which currency the inbound event is in —
    # webhooks can only come from the merchant account we configured.
    provider = PaymentRegistry.get_for_currency("USD")  # any non-INR
    if provider.name != "paypal":
        # Defensive: the non-INR provider got switched to something else
        # but PayPal is still pointing webhooks at us. Reject so the
        # event can be redelivered after admin sorts the config.
        raise AppError(
            "PayPal webhook received but PayPal is not the active "
            "non-INR provider. Check /admin/payment-providers.",
            status_code=503)

    if not provider.verify_webhook(dict(request.headers), body):
        raise AppError("Invalid PayPal webhook signature.", status_code=400)

    event = json.loads(body)
    event_id = event.get("id")
    if not event_id:
        raise AppError("Missing event id", status_code=400)

    if db.query(WebhookEvent).filter_by(event_id=event_id).first():
        return {"received": True, "duplicate": True}

    event_type = event.get("event_type") or ""
    payment = find_payment_for_paypal_event(db, event)
    action = "ignored"

    if payment is not None:
        # Capture the PayPal capture id from the webhook payload too —
        # belt-and-braces, in case /paypal/capture never fired (buyer
        # closed the tab between PayPal approval and our capture call).
        cap_id = (event.get("resource") or {}).get("id")
        if cap_id and not payment.provider_payment_id:
            payment.provider_payment_id = cap_id
            db.flush()

        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            activate_subscription_for_payment(db, payment)
            action = "activated"
        elif event_type == "PAYMENT.CAPTURE.DENIED":
            mark_payment_failed(db, payment)
            action = "failed"
        # PAYMENT.CAPTURE.REFUNDED is intentionally a no-op here —
        # refunds flow through the admin refund endpoint, not via
        # webhook reaction.

    db.add(WebhookEvent(event_id=event_id, payload=event,
                        processed_at=datetime.now(timezone.utc)))
    db.commit()
    return {"received": True, "event_type": event_type, "action": action}
