"""Admin API for lifecycle email automations.

Contract: docs/contracts/email-automation.md

Surfaces (all admin-gated at the parent router):
  GET    /admin/email-automations                 — list mail types
  POST   /admin/email-automations                 — create mail type
  PATCH  /admin/email-automations/{id}            — edit (incl. is_active)
  DELETE /admin/email-automations/{id}            — delete (history kept)
  GET    /admin/email-automations/catalog         — triggers + conditions
  GET    /admin/email-automations/outbox          — Activity feed (R7)
  POST   /admin/email-automations/outbox/{id}/requeue — retry a failure
  POST   /admin/email-automations/{id}/test       — render + send sample
  POST   /admin/email-automations/smtp-test       — REAL SMTP check (R8)
  POST   /admin/email-automations/{id}/bulk-send  — manual send (R9)
"""
import smtplib
import ssl
from datetime import datetime, timezone

import ulid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.settings_store import settings_store
from app.core.tenant import get_current_tenant_id
from app.models.email_automation import (
    EmailAutomation, EmailOutbox, OUTBOX_STATUSES,
)
from app.models.user import User
from app.schemas.email_automation import (
    BulkSendIn, BulkSendOut,
    EmailAutomationCreate, EmailAutomationOut, EmailAutomationUpdate,
    OutboxPageOut, OutboxRowOut, SmtpTestIn, SmtpTestOut, TestSendIn,
)
from app.services.email import mailer
from app.services.email.attachments import total_size_ok
from app.services.email.automation import (
    CONDITION_TYPES, SHARED_PLACEHOLDERS, TRIGGERS,
)

router = APIRouter()


# ------------------------------------------------------------------ helpers
def _validate_payload(data: dict) -> None:
    """Cross-field checks Pydantic can't do without the registries."""
    trigger = data.get("trigger_key")
    if trigger is not None and trigger not in TRIGGERS:
        raise ValidationError(
            f"Unknown trigger '{trigger}'. Valid: {sorted(TRIGGERS)}")
    for cond in (data.get("conditions") or []):
        ctype = cond.get("type") if isinstance(cond, dict) else None
        if ctype not in CONDITION_TYPES:
            raise ValidationError(
                f"Unknown condition type '{ctype}'. "
                f"Valid: {sorted(CONDITION_TYPES)}")
    atts = data.get("attachments")
    if atts is not None and not total_size_ok(atts):
        raise ValidationError("Attachments exceed the 15MB total limit.")


def _sample_ctx(db: Session, admin: User, to: str,
                trigger_key: str) -> dict:
    """Shared placeholders + representative sample values for the
    trigger-specific ones, so a test send shows every substitution."""
    ctx = mailer.build_ctx(db, name=f"{admin.name or 'there'} (preview)",
                           email=to)
    samples = {
        "signup_method": "google", "plan_name": "CPMAI Full Prep",
        "amount": "4999.00", "currency": "INR",
        "expires_at": "31 Dec 2026", "provider": "razorpay",
        "hours_since": "3", "exam_title": "CPMAI Mock Exam 2",
        "score": "82", "passed": "passed", "attempt_date": "03 Jul 2026",
    }
    for key in TRIGGERS.get(trigger_key, {}).get("placeholders", ()):
        ctx[key] = samples.get(key, f"<{key}>")
    return ctx


# ---------------------------------------------------------------- catalog
@router.get("/catalog")
def get_catalog(db: Session = Depends(get_db)):
    """Everything the editor UI needs to stay in sync with the code
    registries: triggers (+placeholder cheat-sheets), condition types,
    send policies. The frontend never hardcodes these."""
    from app.models.email_automation import SEND_POLICIES
    from app.models.exam_set import ExamSet
    exam_sets = [{"id": e.id, "name": e.name}
                 for e in db.query(ExamSet)
                 .order_by(ExamSet.display_order, ExamSet.id).all()]
    return {
        "shared_placeholders": list(SHARED_PLACEHOLDERS),
        "triggers": [
            {"key": k, "label": v["label"],
             "description": v["description"],
             "placeholders": list(v["placeholders"])}
            for k, v in TRIGGERS.items()
        ],
        "condition_types": [
            {"type": k, "label": v["label"], "params": v["params"]}
            for k, v in CONDITION_TYPES.items()
        ],
        "send_policies": list(SEND_POLICIES),
        # For the exam_set_submitted condition picker.
        "exam_sets": exam_sets,
        "master_switch_on": settings_store.get_bool(
            "email.lifecycle_enabled", False),
    }


# ------------------------------------------------------------------- CRUD
@router.get("", response_model=list[EmailAutomationOut])
def list_automations(db: Session = Depends(get_db)):
    return (db.query(EmailAutomation)
            .filter_by(tenant_id=get_current_tenant_id())
            .order_by(EmailAutomation.id)
            .all())


@router.post("", response_model=EmailAutomationOut, status_code=201)
def create_automation(payload: EmailAutomationCreate,
                      db: Session = Depends(get_db),
                      admin: User = Depends(get_admin_user)):
    data = payload.model_dump()
    _validate_payload(data)
    row = EmailAutomation(tenant_id=get_current_tenant_id(), **data)
    db.add(row); db.commit(); db.refresh(row)
    audit_log(db, admin.id, "email_automation.created",
              {"id": row.id, "name": row.name,
               "trigger_key": row.trigger_key})
    return row


@router.patch("/{automation_id}", response_model=EmailAutomationOut)
def update_automation(automation_id: int, payload: EmailAutomationUpdate,
                      db: Session = Depends(get_db),
                      admin: User = Depends(get_admin_user)):
    row = db.get(EmailAutomation, automation_id)
    if not row or row.tenant_id != get_current_tenant_id():
        raise NotFoundError()
    data = payload.model_dump(exclude_unset=True)
    _validate_payload(data)
    for k, v in data.items():
        setattr(row, k, v)
    db.commit(); db.refresh(row)
    audit_log(db, admin.id, "email_automation.updated",
              {"id": automation_id, "fields": list(data.keys())})
    return row


@router.delete("/{automation_id}", status_code=204)
def delete_automation(automation_id: int,
                      db: Session = Depends(get_db),
                      admin: User = Depends(get_admin_user)):
    row = db.get(EmailAutomation, automation_id)
    if not row or row.tenant_id != get_current_tenant_id():
        raise NotFoundError()
    name = row.name
    # Outbox history survives via ON DELETE SET NULL; pending rows for
    # a deleted mail type must not fire later, so cancel them now.
    (db.query(EmailOutbox)
     .filter_by(automation_id=automation_id, status="pending")
     .update({"status": "cancelled",
              "skip_reason": "mail type deleted by admin"}))
    db.delete(row); db.commit()
    audit_log(db, admin.id, "email_automation.deleted",
              {"id": automation_id, "name": name})


# --------------------------------------------------------------- activity
@router.get("/outbox", response_model=OutboxPageOut)
def list_outbox(
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    automation_id: int | None = Query(default=None),
    user_email: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Activity feed (R7): every queued/sent/failed/skipped mail with
    dates + reasons, newest first."""
    if status is not None and status not in OUTBOX_STATUSES:
        raise ValidationError(
            f"status must be one of {OUTBOX_STATUSES}")
    q = (db.query(EmailOutbox, User.email, EmailAutomation.name)
         .join(User, EmailOutbox.user_id == User.id)
         .outerjoin(EmailAutomation,
                    EmailOutbox.automation_id == EmailAutomation.id)
         .filter(EmailOutbox.tenant_id == get_current_tenant_id()))
    if status:
        q = q.filter(EmailOutbox.status == status)
    if automation_id:
        q = q.filter(EmailOutbox.automation_id == automation_id)
    if user_email:
        like = f"%{user_email.strip().lower()}%"
        q = q.filter(User.email.ilike(like))
    total = q.count()
    rows = (q.order_by(EmailOutbox.id.desc())
            .offset(offset).limit(limit).all())
    items = []
    for outbox, email, auto_name in rows:
        item = OutboxRowOut.model_validate(outbox)
        item.user_email = email
        item.automation_name = auto_name
        items.append(item)
    return OutboxPageOut(total=total, items=items)


@router.post("/outbox/{outbox_id}/requeue", response_model=OutboxRowOut)
def requeue_outbox_row(outbox_id: int,
                       db: Session = Depends(get_db),
                       admin: User = Depends(get_admin_user)):
    """Give a failed/skipped/cancelled row another chance — resets it to
    pending, due immediately, with a fresh attempt budget."""
    row = db.get(EmailOutbox, outbox_id)
    if not row or row.tenant_id != get_current_tenant_id():
        raise NotFoundError()
    if row.status == "sent":
        raise ValidationError("This mail was already sent.")
    row.status = "pending"
    row.attempts = 0
    row.last_error = None
    row.skip_reason = None
    row.scheduled_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(row)
    audit_log(db, admin.id, "email_outbox.requeued", {"id": outbox_id})
    user = db.get(User, row.user_id)
    out = OutboxRowOut.model_validate(row)
    out.user_email = user.email if user else row.to_email
    return out


# ------------------------------------------------------------- test sends
@router.post("/{automation_id}/test")
def test_automation(automation_id: int, payload: TestSendIn,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    """Render this mail type with sample values + REAL attachments and
    send it to the admin so they can eyeball it in a live inbox."""
    from app.services.email.attachments import resolve_attachment_paths
    row = db.get(EmailAutomation, automation_id)
    if not row or row.tenant_id != get_current_tenant_id():
        raise NotFoundError()
    to = (payload.to or "").strip() or admin.email
    ctx = _sample_ctx(db, admin, to, row.trigger_key)
    subject = mailer.render_template(row.subject, ctx)
    html = mailer.render_template(row.html_body, ctx)
    paths, bad = resolve_attachment_paths(row.attachments)
    if bad:
        raise ValidationError(f"Attachment problem: {bad}")
    ok = mailer.send_email(to, subject, html, attachments=paths)
    audit_log(db, admin.id, "email_automation.test_sent",
              {"id": automation_id, "to": to, "ok": ok})
    return {"sent": ok, "to": to}


@router.post("/smtp-test", response_model=SmtpTestOut)
def smtp_test(payload: SmtpTestIn,
              db: Session = Depends(get_db),
              admin: User = Depends(get_admin_user)):
    """Email Account tab (R8): real SMTP connect + send, surfacing the
    actual error string instead of the mailer's fail-soft swallow. This
    is how the admin distinguishes 'saved' from 'working'."""
    to = (payload.to or "").strip() or admin.email
    host = settings_store.get_str("email.smtp_host", "")
    port = settings_store.get_int("email.smtp_port", 465)
    use_ssl = settings_store.get_bool("email.smtp_use_ssl", True)
    username = settings_store.get_str("email.smtp_username", "")
    password = settings_store.get_str("email.smtp_password", "")
    from_addr = settings_store.get_str("email.from_address", username)
    from_name = settings_store.get_str("email.from_name", "")

    missing = [label for label, v in (
        ("smtp host", host), ("from address", from_addr))
        if not v]
    if missing:
        return SmtpTestOut(ok=False, to=to,
                           error=f"Not configured yet: {', '.join(missing)}")

    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = "CPMAI Prep — SMTP configuration test"
    msg["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
    msg["To"] = to
    msg.set_content(
        "This is a test email from the CPMAI Prep admin panel.\n"
        "If you can read this, the SMTP configuration works.")
    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                if username and password:
                    s.login(username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                if username and password:
                    s.login(username, password)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        error = f"Authentication failed — check username/password ({e.smtp_code})"
    except smtplib.SMTPException as e:
        error = f"SMTP error: {e}"
    except OSError as e:
        error = f"Connection failed — check host/port/SSL: {e}"
    else:
        error = None
    audit_log(db, admin.id, "email_smtp.test",
              {"to": to, "ok": error is None,
               "error": error})
    return SmtpTestOut(ok=error is None, to=to, error=error)


# -------------------------------------------------------------- bulk send
@router.post("/{automation_id}/bulk-send", response_model=BulkSendOut)
def bulk_send(automation_id: int, payload: BulkSendIn,
              db: Session = Depends(get_db),
              admin: User = Depends(get_admin_user)):
    """Manual send to admin-selected users (R9). One personalized outbox
    row per user, due immediately. Conditions are NOT applied — the
    admin explicitly chose the recipients; personalization always is.
    Sends still require the master switch ON at dispatch time."""
    row = db.get(EmailAutomation, automation_id)
    if not row or row.tenant_id != get_current_tenant_id():
        raise NotFoundError()
    now = datetime.now(timezone.utc)
    tenant_id = get_current_tenant_id()
    queued, skipped = 0, []
    for uid in dict.fromkeys(payload.user_ids):   # de-dupe, keep order
        user = db.get(User, uid)
        if user is None or user.deleted_at is not None:
            skipped.append({"user_id": uid, "reason": "user not found"})
            continue
        if not user.email:
            skipped.append({"user_id": uid, "reason": "no email address"})
            continue
        db.add(EmailOutbox(
            tenant_id=tenant_id,
            automation_id=row.id,
            user_id=user.id,
            to_email=user.email,
            dedup_key=f"manual:{row.id}:{user.id}:{ulid.new()}",
            scheduled_at=now,
            status="pending",
            source="manual",
            context={"signup_method":
                     "google" if user.google_id else "password"},
        ))
        queued += 1
    db.commit()
    audit_log(db, admin.id, "email_automation.bulk_send",
              {"id": automation_id, "queued": queued,
               "skipped": len(skipped)})
    return BulkSendOut(queued=queued, skipped=skipped)
