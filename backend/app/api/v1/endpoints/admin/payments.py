"""Admin payments visibility — captured / failed / abandoned follow-up.

Contract: docs/contracts/email-automation.md §8 (R10)

Read-only in v1: the follow-up ACTIONS are either manual (admin emails
the user from the list) or automated via the payment.failed /
payment.abandoned mail types. "Abandoned" is a *view*, not a stored
status — an order that sat in ``created`` longer than the requested
threshold. We deliberately don't mutate Payment.status for abandonment:
a user can still complete an old Razorpay/PayPal order, and the webhook
must find the row in its expected state.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.models.payment import Payment
from app.models.payment_provider import PaymentProviderConfig
from app.models.plan import Plan
from app.models.user import User

router = APIRouter()

_STATUSES = ("created", "captured", "failed", "refunded")


@router.get("")
def list_payments(
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    abandoned_hours: int | None = Query(default=None, ge=1, le=24 * 30),
    user_email: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Paginated payment list with user + plan context.

    ``abandoned_hours=N`` narrows to status='created' rows older than N
    hours (implies status=created; passing both with a conflicting
    status is a validation error, not a silent override).
    """
    if status is not None and status not in _STATUSES:
        raise ValidationError(f"status must be one of {_STATUSES}")
    if abandoned_hours is not None and status not in (None, "created"):
        raise ValidationError(
            "abandoned_hours only combines with status=created")

    q = (db.query(Payment, User.email, User.name, Plan.name,
                  PaymentProviderConfig.display_name,
                  PaymentProviderConfig.name)
         .join(User, Payment.user_id == User.id)
         .outerjoin(Plan, Payment.plan_id == Plan.id)
         .outerjoin(PaymentProviderConfig,
                    Payment.provider_config_id == PaymentProviderConfig.id))
    if abandoned_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=abandoned_hours)
        q = q.filter(Payment.status == "created",
                     Payment.created_at <= cutoff)
    elif status:
        q = q.filter(Payment.status == status)
    if user_email:
        q = q.filter(User.email.ilike(f"%{user_email.strip().lower()}%"))
    total = q.count()
    rows = (q.order_by(Payment.id.desc())
            .offset(offset).limit(limit).all())
    return {
        "total": total,
        "items": [
            {
                "id": p.id,
                "user_id": p.user_id,
                "user_email": email,
                "user_name": uname,
                "plan_name": plan_name,
                "provider_name": p.provider_name,
                "provider_order_id": p.provider_order_id,
                "amount_paise": p.amount_paise,
                "currency": p.currency,
                "status": p.status,
                "offer_code": p.offer_code,
                "created_at": p.created_at,
                # Which ACCOUNT took the money (Personal vs Company
                # Razorpay); falls back to provider_name for
                # pre-0047 rows and manual payments.
                "provider_account": (acct_display or acct_name
                                     or p.provider_name),
                "invoice_number": p.invoice_number,
                "invoice_email_status": p.invoice_email_status,
                "invoice_email_sent_at": p.invoice_email_sent_at,
            }
            for p, email, uname, plan_name, acct_display, acct_name in rows
        ],
    }


@router.get("/{payment_id}/invoice")
def download_invoice(payment_id: int, db: Session = Depends(get_db)):
    """Stream the invoice PDF (generating it on first request). Only
    captured/refunded payments have invoices — money must have moved."""
    p = db.get(Payment, payment_id)
    if p is None:
        raise NotFoundError()
    if p.status not in ("captured", "refunded"):
        raise ValidationError(
            "No invoice: payment was never captured.")
    from app.services.invoice import ensure_invoice_pdf
    path = ensure_invoice_pdf(db, p)
    return FileResponse(str(path), media_type="application/pdf",
                        filename=f"{p.invoice_number}.pdf")


@router.post("/{payment_id}/mark-paid")
def mark_paid(payment_id: int, db: Session = Depends(get_db),
              admin: User = Depends(get_admin_user)):
    """Operator backstop: the gateway shows the money ARRIVED (e.g. a
    PayPal payment that sat 'waiting for acceptance' and was accepted
    manually) but cpmai recorded created/failed. Flips the payment to
    captured through the normal activation path — subscription granted
    or extended, offer redemption recorded, invoice generated and
    emailed — exactly as if the webhook had arrived. Idempotent on
    already-captured rows."""
    p = db.get(Payment, payment_id)
    if p is None:
        raise NotFoundError()
    if p.status == "refunded":
        raise ValidationError("Payment was refunded — grant a fresh "
                              "subscription instead of re-capturing.")
    prior = p.status
    from app.services.payment_lifecycle import (
        activate_subscription_for_payment,
    )
    sub = activate_subscription_for_payment(db, p)
    audit_log(db, admin.id, "admin.payment.mark_paid", {
        "payment_id": p.id,
        "target_user_id": p.user_id,
        "prior_status": prior,
        "provider_order_id": p.provider_order_id,
        "amount_paise": p.amount_paise,
        "currency": p.currency,
    })
    return {"status": p.status, "prior_status": prior,
            "subscription_id": sub.id,
            "invoice_email_status": p.invoice_email_status}


@router.post("/{payment_id}/invoice/send")
def send_invoice(payment_id: int, db: Session = Depends(get_db)):
    """(Re)send the invoice email now, synchronously, so the operator
    sees the real SMTP outcome instead of a fire-and-forget promise."""
    p = db.get(Payment, payment_id)
    if p is None:
        raise NotFoundError()
    if p.status not in ("captured", "refunded"):
        raise ValidationError(
            "No invoice: payment was never captured.")
    from app.services.invoice import send_invoice_email
    ok = send_invoice_email(db, p, force=True)
    return {"sent": ok,
            "invoice_number": p.invoice_number,
            "invoice_email_status": p.invoice_email_status}


@router.get("/summary")
def payments_summary(db: Session = Depends(get_db)):
    """Status counts for the page header chips (+ abandoned-24h)."""
    from sqlalchemy import func as sa_func
    counts = dict(
        db.query(Payment.status, sa_func.count(Payment.id))
        .group_by(Payment.status).all())
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    abandoned = (db.query(Payment)
                 .filter(Payment.status == "created",
                         Payment.created_at <= cutoff)
                 .count())
    return {
        "by_status": {s: counts.get(s, 0) for s in _STATUSES},
        "abandoned_24h": abandoned,
    }
