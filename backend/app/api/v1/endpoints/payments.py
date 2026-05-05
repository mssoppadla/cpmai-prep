"""Payment endpoints — now use PaymentRegistry (no env-coupled singleton)."""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_current_user
from app.core.exceptions import AppError, NotFoundError
from app.core.audit import audit_log
from app.core.limiter import limiter
from app.models.user import User
from app.models.payment import Payment, WebhookEvent
from app.models.subscription import Subscription
from app.schemas.payment import (
    CreateOrderIn, CreateOrderOut, VerifyPaymentIn,
)
from app.services.payment_registry import PaymentRegistry
from app.services.tracking_service import emit_event

router = APIRouter()


@router.post("/orders", response_model=CreateOrderOut, status_code=201)
def create_order(payload: CreateOrderIn,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    provider = PaymentRegistry.get_active()
    receipt = f"u_{user.id}_{int(datetime.now().timestamp())}"
    order = provider.create_order(payload.amount_paise, receipt=receipt)
    db.add(Payment(
        user_id=user.id,
        razorpay_order_id=order["id"],
        amount_paise=payload.amount_paise,
        currency="INR",
        status="created",
        idempotency_key=receipt,
    ))
    db.commit()
    emit_event(db, "payment.order_created", user_id=user.id,
               metadata={"order_id": order["id"], "plan": payload.plan})
    return CreateOrderOut(
        order_id=order["id"], amount=order["amount"],
        currency=order["currency"], razorpay_key_id=provider.key_id,
    )


@router.post("/verify")
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
    payment.razorpay_payment_id = payload.payment_id
    payment.status = "captured"

    sub = db.query(Subscription).filter_by(user_id=user.id, status="active").first()
    if not sub:
        sub = Subscription(user_id=user.id, plan=payload.plan, status="active")
        db.add(sub)

    db.commit()
    emit_event(db, "payment.success", user_id=user.id,
               metadata={"plan": payload.plan, "amount": payment.amount_paise})
    audit_log(db, user.id, "payment.success",
              {"plan": payload.plan, "order_id": payload.order_id})
    return {"status": "active", "plan": payload.plan}


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
