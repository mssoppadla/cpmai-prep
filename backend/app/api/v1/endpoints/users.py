from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.core.audit import audit_log
from app.core.deps import get_db, get_current_user
from app.models.assistant_log import AssistantLog
from app.models.exam_session import ExamSession
from app.models.lead import Lead
from app.models.payment import Payment
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.auth import (
    SubscriptionSummary, UserDashboardOut, UserOut,
)

router = APIRouter()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/me/dashboard", response_model=UserDashboardOut)
def my_dashboard(user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Self-view for the learner home page.

    Bundles user identity + subscription state in one round-trip so the
    dashboard can render without a second fetch. Active subscription is
    the most recent row with status='active' (the model allows multiple
    rows over time as plans change).
    """
    sub = (db.query(Subscription)
           .filter_by(user_id=user.id, status="active")
           .order_by(Subscription.created_at.desc()).first())
    return UserDashboardOut(
        user=UserOut.model_validate(user),
        subscription=SubscriptionSummary(
            active=bool(sub),
            plan=sub.plan if sub else None,
            status=sub.status if sub else None,
            current_period_end=sub.current_period_end if sub else None,
        ),
        has_google=bool(user.google_id),
        has_password=bool(user.password_hash),
    )


# ---------------------------------------------------------------------------
# GDPR self-service: data export + account deletion.
# ---------------------------------------------------------------------------


@router.get("/me/export")
def export_my_data(user: User = Depends(get_current_user),
                   db: Session = Depends(get_db),
                   request: Request = None):
    """Return everything we hold for this user as inline JSON.

    Inline rather than zip-via-email because typical accounts are small
    (a handful of attempts, a few payments, some chat turns). If a user
    is on a much larger plan and this becomes slow, swap to a
    BackgroundTask that streams to S3 and emails a signed link — the
    contract here (single JSON object keyed by collection) is stable.

    Financial rows (payments, subscriptions) are INCLUDED in the export
    even though they're retained on delete — the user has a right to
    see them, just not to remove them. Assistant-log inputs are already
    PII-redacted at capture; we return the redacted form here too.
    """
    sessions = db.query(ExamSession).filter_by(user_id=user.id).all()
    payments = db.query(Payment).filter_by(user_id=user.id).all()
    subs = db.query(Subscription).filter_by(user_id=user.id).all()
    logs = (db.query(AssistantLog)
            .filter_by(user_id=user.id)
            .order_by(AssistantLog.created_at.desc()).all())
    leads = db.query(Lead).filter(Lead.email == user.email).all()

    audit_log(db, user.id, "user.data_exported",
              ip=getattr(request.state, "ip", None) if request else None,
              user_agent=request.headers.get("user-agent") if request else None,
              request_id=getattr(request.state, "request_id", None) if request else None)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user": {
            "id": user.id, "email": user.email, "name": user.name,
            "role": user.role.value, "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "has_google": bool(user.google_id),
            "has_password": bool(user.password_hash),
        },
        "exam_attempts": [{
            "id": s.id, "exam_set_id": s.exam_set_id,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
            "status": s.status, "score": s.score, "passed": s.passed,
            "time_taken_seconds": s.time_taken_seconds,
        } for s in sessions],
        "subscriptions": [{
            "id": s.id, "plan": s.plan, "plan_id": s.plan_id,
            "status": s.status,
            "current_period_start": s.current_period_start.isoformat() if s.current_period_start else None,
            "current_period_end": s.current_period_end.isoformat() if s.current_period_end else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "cancelled_at": s.cancelled_at.isoformat() if s.cancelled_at else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        } for s in subs],
        "payments": [{
            "id": p.id, "subscription_id": p.subscription_id,
            "plan_id": p.plan_id,
            "amount_paise": p.amount_paise, "currency": p.currency,
            "status": p.status, "offer_code": p.offer_code,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        } for p in payments],
        "assistant_log": [{
            "id": l.id, "intent": l.intent, "provider": l.provider,
            "model": l.model,
            "redacted_input": l.redacted_input,
            "response_preview": l.response_preview,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        } for l in logs],
        "leads": [{
            "id": ld.id, "source": ld.source.value,
            "phone": ld.phone, "company": ld.company, "role": ld.role,
            "consent_marketing": ld.consent_marketing,
            "created_at": ld.created_at.isoformat() if ld.created_at else None,
        } for ld in leads],
    }


@router.delete("/me", status_code=204)
def delete_my_account(user: User = Depends(get_current_user),
                      db: Session = Depends(get_db),
                      request: Request = None):
    """GDPR account deletion: soft-delete + PII redaction.

    Delegates to ``app.services.user_deletion.soft_delete_user`` so the
    redaction contract stays in lockstep with the admin-triggered
    delete path (``DELETE /admin/users/{id}``). See that module for
    the full contract + rationale.

    Idempotent: calling on an already-deleted user is a no-op (the
    auth layer would have rejected the token before reaching here, but
    we handle it defensively).
    """
    from app.services.user_deletion import soft_delete_user
    soft_delete_user(db, user)

    audit_log(db, user.id, "user.self_deleted",
              ip=getattr(request.state, "ip", None) if request else None,
              user_agent=request.headers.get("user-agent") if request else None,
              request_id=getattr(request.state, "request_id", None) if request else None)
