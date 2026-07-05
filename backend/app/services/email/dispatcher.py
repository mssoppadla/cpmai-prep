"""Outbox dispatcher — drains due lifecycle emails on a 60s tick.

Contract: docs/contracts/email-automation.md §5

Registered on the SHARED AsyncIOScheduler in app/main.py startup (same
pattern as the visitor-insights rollup — one scheduler, many jobs).
Skipped when APP_ENV=test; tests call ``dispatch_due()`` directly with
their own session.

Every state transition lands on the outbox row itself (status + date +
error/skip reason) because that row IS the admin's Activity view — the
whole point of R7 is that the admin never has to wonder whether a mail
went out.

Restart-safe by construction: the queue is Postgres, the tick is
stateless. A deploy mid-wait loses nothing — the next tick picks up
where the old process stopped.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.core.settings_store import settings_store
from app.models.email_automation import EmailAutomation, EmailOutbox
from app.models.user import User

log = structlog.get_logger("email.dispatcher")

# Cap per tick so a backlog (e.g. after re-enabling the master switch)
# drains gradually instead of hammering the SMTP relay in one burst.
BATCH_SIZE = 50
MAX_ATTEMPTS = 3
TICK_SECONDS = 60


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the dispatcher tick + abandoned-payment sweeper to the
    shared scheduler. Idempotent (replace_existing)."""
    scheduler.add_job(
        run_dispatch_tick,
        trigger=IntervalTrigger(seconds=TICK_SECONDS),
        id="email:outbox-dispatch",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=TICK_SECONDS,
    )
    scheduler.add_job(
        run_abandoned_sweep,
        trigger=IntervalTrigger(minutes=15),
        id="email:abandoned-sweep",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    log.info("email.dispatcher_registered")


def run_dispatch_tick() -> int:
    """Scheduler entrypoint — opens its own session."""
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        return dispatch_due(db)


def run_abandoned_sweep() -> int:
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        return sweep_abandoned_payments(db)


def dispatch_due(db: Session, now: datetime | None = None) -> int:
    """Send every due pending outbox row. Returns number sent.

    Master switch OFF → rows stay pending untouched (they send when the
    admin flips it back on — deliberate: the switch pauses, not purges).
    """
    if not settings_store.get_bool("email.lifecycle_enabled", False):
        return 0
    now = now or datetime.now(timezone.utc)
    rows = (db.query(EmailOutbox)
            .filter(EmailOutbox.status == "pending",
                    EmailOutbox.scheduled_at <= now)
            .order_by(EmailOutbox.scheduled_at)
            .limit(BATCH_SIZE)
            .all())
    sent = 0
    for row in rows:
        try:
            if _dispatch_one(db, row, now):
                sent += 1
        except Exception as e:  # noqa: BLE001 — one bad row ≠ dead queue
            db.rollback()
            log.error("email.dispatch_row_crashed", outbox_id=row.id,
                      error=str(e))
    return sent


def _dispatch_one(db: Session, row: EmailOutbox, now: datetime) -> bool:
    from app.core.audit import audit_log
    from app.services.email import mailer
    from app.services.email.attachments import resolve_attachment_paths
    from app.services.email.automation import evaluate_conditions

    auto = (db.get(EmailAutomation, row.automation_id)
            if row.automation_id else None)
    if auto is None:
        return _skip(db, row, "automation deleted")

    user = db.get(User, row.user_id)
    if user is None or user.deleted_at is not None:
        return _skip(db, row, "user deleted")

    # Send-time rechecks (contract §2) — automation rows only. Manual
    # bulk sends bypass BOTH the per-type toggle and the conditions:
    # the admin explicitly picked the template and the recipients (a
    # mail type can be kept disabled precisely because it's meant for
    # manual blasts only). The master switch above still gates manual
    # sends — it's the global kill switch.
    if row.source == "automation":
        if not auto.is_active:
            return _skip(db, row, "mail type disabled by admin")
        ok, reason = evaluate_conditions(db, user, auto.conditions)
        if not ok:
            return _skip(db, row, reason)

    ctx = mailer.build_ctx(db, name=user.name, email=row.to_email)
    ctx.update(row.context or {})
    subject = mailer.render_template(auto.subject, ctx)
    html = mailer.render_template(auto.html_body, ctx)
    paths, bad = resolve_attachment_paths(auto.attachments)
    if bad:
        # A vanished/escaping attachment file must not silently send a
        # mail missing the PDF the admin promised — fail visibly.
        return _fail(db, row, f"attachment unavailable: {bad}", now)

    ok = mailer.send_email(row.to_email, subject, html, attachments=paths)
    if ok:
        row.attempts = (row.attempts or 0) + 1
        row.status = "sent"
        row.sent_at = now
        row.context = {**(row.context or {}), "_subject": subject}
        db.commit()
        # NB: metadata keys must not collide with audit_log's own
        # structlog kwargs (user_id/action/tenant_id) — hence
        # recipient_user_id, not user_id.
        audit_log(db, None, "email.lifecycle_sent",
                  {"outbox_id": row.id, "automation_id": auto.id,
                   "recipient_user_id": row.user_id, "to": row.to_email})
        return True
    return _fail(db, row, "smtp send failed (see email log)", now)


def _skip(db: Session, row: EmailOutbox, reason: str) -> bool:
    row.status = "skipped"
    row.skip_reason = reason[:240]
    db.commit()
    log.info("email.dispatch_skipped", outbox_id=row.id, reason=reason)
    return False


def _fail(db: Session, row: EmailOutbox, error: str,
          now: datetime) -> bool:
    row.attempts = (row.attempts or 0) + 1
    row.last_error = error[:2000]
    if row.attempts >= MAX_ATTEMPTS:
        row.status = "failed"
    else:
        # Stay pending; next tick retries (spacing = tick interval).
        row.scheduled_at = now + timedelta(seconds=TICK_SECONDS)
    db.commit()
    log.warning("email.dispatch_failed", outbox_id=row.id,
                attempts=row.attempts, error=error)
    return False


def sweep_abandoned_payments(db: Session,
                             now: datetime | None = None) -> int:
    """Enqueue ``payment.abandoned`` automations for orders stuck in
    ``created``. The automation's delay_minutes doubles as the
    abandonment threshold (contract §3): an order older than the delay
    is abandoned, and dedup ref = payment id keeps it to one nudge per
    order per automation.
    """
    from app.core.tenant import get_current_tenant_id
    from app.models.payment import Payment
    from app.services.email.automation import enqueue_for_trigger

    if not settings_store.get_bool("email.lifecycle_enabled", False):
        return 0
    now = now or datetime.now(timezone.utc)
    autos = (db.query(EmailAutomation)
             .filter_by(tenant_id=get_current_tenant_id(),
                        trigger_key="payment.abandoned", is_active=True)
             .all())
    if not autos:
        return 0
    queued = 0
    # Look back 7 days max — older stragglers predate the feature and
    # a "you left something in your cart" mail weeks later reads wrong.
    horizon = now - timedelta(days=7)
    for auto in autos:
        threshold = now - timedelta(minutes=auto.delay_minutes or 60)
        stale = (db.query(Payment)
                 .filter(Payment.status == "created",
                         Payment.created_at <= threshold,
                         Payment.created_at >= horizon)
                 .all())
        for p in stale:
            user = db.get(User, p.user_id)
            if user is None:
                continue
            from app.models.plan import Plan
            plan = db.get(Plan, p.plan_id) if p.plan_id else None
            hours = int((now - p.created_at).total_seconds() // 3600) \
                if p.created_at else 0
            queued += enqueue_for_trigger(
                db, "payment.abandoned", user,
                event_ref=f"pay{p.id}",
                context_extra={
                    "plan_name": plan.name if plan else "",
                    "amount": f"{(p.amount_paise or 0) / 100:.2f}",
                    "currency": p.currency,
                    "hours_since": str(hours),
                })
    return queued
