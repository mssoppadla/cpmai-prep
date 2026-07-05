"""Lifecycle email automation — trigger catalog, conditions, enqueue.

Contract: docs/contracts/email-automation.md

The engine in one sentence: a lifecycle hook fires (signup / payment /
exam submit / sweeper) → ``enqueue_for_trigger()`` finds the admin's
active automations for that trigger, evaluates their conditions, and
inserts ``EmailOutbox`` rows scheduled ``delay_minutes`` in the future;
the dispatcher (dispatcher.py) drains due rows and sends.

Everything the admin configures (mail types, conditions, timing,
content, attachments) is data. The two code-defined registries here —
TRIGGERS and CONDITION_TYPES — are the extension points that DO need a
code change, because a trigger must be instrumented where the event
happens. Both are additive-only: removing/renaming an entry that admin
rows may reference is a contract violation (unknown values degrade to
skip-with-WARN, never an error).

Fail-soft discipline: enqueue runs inside request paths (signup, verify,
exam submit). It must NEVER break them — same rule as emit_event().
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import structlog
import ulid
from sqlalchemy.orm import Session

from app.core.tenant import get_current_tenant_id
from app.models.email_automation import EmailAutomation, EmailOutbox
from app.models.subscription import Subscription
from app.models.user import User

log = structlog.get_logger("email.automation")


# --------------------------------------------------------------------------
# Trigger catalog (code-defined, additive-only — contract §3)
#
# ``placeholders`` lists what the admin can use IN ADDITION to the shared
# set below; surfaced verbatim in the editor cheat-sheet via
# GET /admin/email-automations/catalog.
# ``ref``: how the every_event dedup ref is derived from the event kwargs.
# --------------------------------------------------------------------------
SHARED_PLACEHOLDERS = (
    "name", "email", "brand_name", "enroll_url",
    "offer_code", "offer_valid_until",
)

TRIGGERS: dict[str, dict] = {
    "user.signup": {
        "label": "User signed up",
        "description": "Fires once when an account is created "
                       "(password or Google).",
        "placeholders": ("signup_method",),
    },
    "user.login": {
        "label": "User logged in",
        "description": "Fires on every login. Combine with conditions "
                       "and a send policy/cooldown to avoid spam.",
        "placeholders": ("signup_method",),
    },
    "payment.success": {
        "label": "Payment received",
        "description": "Fires when a payment is captured and the "
                       "subscription activates (Razorpay or PayPal).",
        "placeholders": ("plan_name", "amount", "currency", "expires_at"),
    },
    "payment.failed": {
        "label": "Payment failed",
        "description": "Fires when the gateway reports a failed payment.",
        "placeholders": ("plan_name", "amount", "currency", "provider"),
    },
    "payment.abandoned": {
        "label": "Checkout abandoned",
        "description": "Fires when an order sits unpaid for the "
                       "configured wait time (delay doubles as the "
                       "abandonment threshold).",
        "placeholders": ("plan_name", "amount", "currency", "hours_since"),
    },
    "exam.submitted": {
        "label": "Exam submitted",
        "description": "Fires when a signed-in user submits an exam "
                       "attempt.",
        "placeholders": ("exam_title", "score", "passed", "attempt_date"),
    },
}


# --------------------------------------------------------------------------
# Condition types (code-defined, additive-only — contract §4)
#
# Each evaluator: (db, user, params) -> bool. Conditions are checked at
# enqueue AND re-checked at send time (dispatcher), so "user paid during
# the 20-minute wait" correctly skips the unpaid-nudge mail.
# --------------------------------------------------------------------------

def _has_active_subscription(db: Session, user: User, params: dict) -> bool:
    now = datetime.now(timezone.utc)
    row = (db.query(Subscription)
           .filter(Subscription.user_id == user.id,
                   Subscription.status == "active",
                   Subscription.revoked_at.is_(None))
           .filter((Subscription.expires_at.is_(None))
                   | (Subscription.expires_at > now))
           .first())
    return (row is not None) == bool(params.get("value", True))


def _signup_method(db: Session, user: User, params: dict) -> bool:
    want = str(params.get("value", "")).lower()
    if want == "google":
        return user.google_id is not None
    if want == "password":
        return user.password_hash is not None
    return True  # unknown/blank value — treat as always-true, not a trap


def _exam_set_submitted(db: Session, user: User, params: dict) -> bool:
    from app.models.exam_session import ExamSession
    exam_set_id = params.get("exam_set_id")
    if not isinstance(exam_set_id, int):
        return True  # malformed row — fail open, editor validates on write
    row = (db.query(ExamSession)
           .filter_by(user_id=user.id, exam_set_id=exam_set_id,
                      status="submitted")
           .first())
    return (row is not None) == bool(params.get("value", True))


def _days_since_signup(db: Session, user: User, params: dict) -> bool:
    if user.created_at is None:
        return True
    days = (datetime.now(timezone.utc) - user.created_at).days
    try:
        threshold = int(params.get("days", 0))
    except (TypeError, ValueError):
        return True
    return days < threshold if params.get("op") == "lt" else days > threshold


CONDITION_TYPES: dict[str, dict] = {
    "has_active_subscription": {
        "label": "Payment status",
        "evaluator": _has_active_subscription,
        "params": {"value": "bool — true = has paid, false = has not paid"},
    },
    "signup_method": {
        "label": "Signup method",
        "evaluator": _signup_method,
        "params": {"value": "google | password"},
    },
    "exam_set_submitted": {
        "label": "Exam set submitted",
        "evaluator": _exam_set_submitted,
        "params": {"exam_set_id": "int", "value":
                   "bool — true = has submitted, false = has not"},
    },
    "days_since_signup": {
        "label": "Days since signup",
        "evaluator": _days_since_signup,
        "params": {"op": "lt | gt", "days": "int"},
    },
}


def evaluate_conditions(db: Session, user: User,
                        conditions: list | None) -> tuple[bool, str]:
    """AND all condition rows. Returns (matches, reason-if-not).

    Unknown condition types fail CLOSED here (skip + reason) — the API
    validates on write, so an unknown type in the DB means version skew
    and silently sending would be the riskier behaviour.
    """
    for cond in (conditions or []):
        if not isinstance(cond, dict):
            return False, "malformed condition row"
        ctype = cond.get("type")
        spec = CONDITION_TYPES.get(ctype)
        if spec is None:
            return False, f"unknown condition type '{ctype}'"
        try:
            if not spec["evaluator"](db, user, cond):
                return False, f"condition not met: {ctype}"
        except Exception as e:  # noqa: BLE001 — never break the caller
            log.warning("email.condition_error", type=ctype, error=str(e))
            return False, f"condition errored: {ctype}"
    return True, ""


def build_dedup_key(automation: EmailAutomation, user_id: int,
                    event_ref: str | None) -> str:
    """Per-policy duplicate-send guard (contract §2).

    once_per_user   → one row ever per user+automation.
    replace_pending → single logical slot; a new event UPDATES the
                      pending row instead of inserting (see enqueue).
    every_event     → unique per triggering event; caller supplies a
                      stable ref (payment id / exam session id) so the
                      verify-vs-webhook race can't double-send. Falls
                      back to a ULID when no natural ref exists.
    """
    if automation.send_policy == "once_per_user":
        ref = "once"
    elif automation.send_policy == "replace_pending":
        ref = "latest"
    else:
        ref = event_ref or str(ulid.new())
    return f"{automation.id}:{user_id}:{ref}"


def enqueue_for_trigger(db: Session, trigger_key: str, user: User, *,
                        event_ref: str | None = None,
                        context_extra: dict | None = None) -> int:
    """Queue outbox rows for every active automation on ``trigger_key``.

    Called from lifecycle hooks (auth/payment/exam). Fail-soft: any
    error is logged and swallowed; returns how many rows were queued.

    ``context_extra`` carries trigger-specific placeholder values that
    only the hook site knows (plan_name, score, …). They're snapshotted
    into the outbox row so dispatch doesn't need to re-derive them.
    """
    try:
        return _enqueue(db, trigger_key, user,
                        event_ref=event_ref,
                        context_extra=context_extra or {})
    except Exception as e:  # noqa: BLE001 — never break the request path
        log.warning("email.enqueue_failed", trigger=trigger_key,
                    user_id=getattr(user, "id", None), error=str(e))
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0


def _enqueue(db: Session, trigger_key: str, user: User, *,
             event_ref: str | None, context_extra: dict) -> int:
    if user is None or not user.email or user.deleted_at is not None:
        return 0
    now = datetime.now(timezone.utc)
    tenant_id = get_current_tenant_id()
    rows = (db.query(EmailAutomation)
            .filter_by(tenant_id=tenant_id, trigger_key=trigger_key,
                       is_active=True)
            .all())
    queued = 0
    for auto in rows:
        ok, reason = evaluate_conditions(db, user, auto.conditions)
        if not ok:
            log.debug("email.enqueue_skipped", automation_id=auto.id,
                      user_id=user.id, reason=reason)
            continue
        dedup = build_dedup_key(auto, user.id, event_ref)
        scheduled = now + timedelta(minutes=auto.delay_minutes or 0)

        existing = (db.query(EmailOutbox)
                    .filter_by(dedup_key=dedup).first())
        if existing is not None:
            if (auto.send_policy == "replace_pending"
                    and existing.status == "pending"):
                # New qualifying event resets the clock + snapshot: the
                # user gets ONE mail, delay after their LATEST event.
                existing.scheduled_at = scheduled
                existing.context = {**(existing.context or {}),
                                    **context_extra}
                db.commit()
                queued += 1
            # once_per_user / already-settled rows: silently deduped.
            continue

        if auto.send_policy == "every_event" and auto.cooldown_days:
            window = now - timedelta(days=auto.cooldown_days)
            recent = (db.query(EmailOutbox)
                      .filter(EmailOutbox.automation_id == auto.id,
                              EmailOutbox.user_id == user.id,
                              EmailOutbox.status == "sent",
                              EmailOutbox.sent_at >= window)
                      .first())
            if recent is not None:
                log.debug("email.enqueue_cooldown", automation_id=auto.id,
                          user_id=user.id)
                continue

        db.add(EmailOutbox(
            tenant_id=tenant_id,
            automation_id=auto.id,
            user_id=user.id,
            to_email=user.email,
            dedup_key=dedup,
            scheduled_at=scheduled,
            status="pending",
            source="automation",
            context=dict(context_extra),
        ))
        db.commit()
        queued += 1
        log.info("email.enqueued", automation_id=auto.id,
                 user_id=user.id, trigger=trigger_key,
                 scheduled_at=scheduled.isoformat())
    return queued


def cancel_unpaid_nudges(db: Session, user_id: int) -> int:
    """Payment succeeded → cancel pending signup/login nudges whose
    conditions target unpaid users (contract §3). The dispatcher's
    send-time recheck would skip them anyway; cancelling makes the
    Activity tab tell the truth immediately ("cancelled — user paid").
    """
    try:
        rows = (db.query(EmailOutbox)
                .join(EmailAutomation,
                      EmailOutbox.automation_id == EmailAutomation.id)
                .filter(EmailOutbox.user_id == user_id,
                        EmailOutbox.status == "pending",
                        EmailAutomation.trigger_key.in_(
                            ("user.signup", "user.login")))
                .all())
        n = 0
        for row in rows:
            auto = db.get(EmailAutomation, row.automation_id)
            targets_unpaid = any(
                isinstance(c, dict)
                and c.get("type") == "has_active_subscription"
                and not c.get("value", True)
                for c in (auto.conditions or []))
            if targets_unpaid:
                row.status = "cancelled"
                row.skip_reason = "cancelled — user paid before send"
                n += 1
        if n:
            db.commit()
            log.info("email.nudges_cancelled", user_id=user_id, count=n)
        return n
    except Exception as e:  # noqa: BLE001 — fail-soft on payment path
        log.warning("email.cancel_nudges_failed", user_id=user_id,
                    error=str(e))
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0
