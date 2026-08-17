"""Reconciliation sweep — find gateway-captured money cpmai missed.

The 2026-08-17 incident: browser verification failed (since fixed) AND
the account's webhook was disabled at Razorpay → a real UPI payment sat
as "unpaid (created)" until the operator noticed. This sweep closes
that class structurally: for recent 'created' Razorpay orders, ask the
gateway directly whether a captured payment exists, and if so activate
through the exact same lifecycle path a webhook would have used
(idempotent, invoice included, captured_via='reconcile').

Runs hourly on the shared APScheduler (registered in app.main next to
the email dispatcher). Master switch: payments.reconcile_enabled.
Fail-soft per row — one gateway hiccup never aborts the sweep.

PayPal rows are skipped for now (different API; PayPal's own webhook +
capture flow already covers its cases).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

from app.core.settings_store import settings_store
from app.models.payment import Payment

log = structlog.get_logger("payment_reconcile")

# Only look at orders old enough that the in-browser flow clearly
# didn't finish, and young enough that the customer plausibly paid.
MIN_AGE_MINUTES = 30
MAX_AGE_DAYS = 7
BATCH = 50


def reconcile_created_payments(db: Session, now: datetime | None = None) -> dict:
    """One sweep pass. Returns counters for logging/tests."""
    if not settings_store.get_bool("payments.reconcile_enabled", True):
        return {"checked": 0, "healed": 0, "skipped": 0, "errors": 0}
    now = now or datetime.now(timezone.utc)
    newest = now - timedelta(minutes=MIN_AGE_MINUTES)
    oldest = now - timedelta(days=MAX_AGE_DAYS)
    rows = (db.query(Payment)
            .filter(Payment.status == "created",
                    Payment.provider_name == "razorpay",
                    Payment.created_at <= newest,
                    Payment.created_at >= oldest)
            .order_by(Payment.id.desc())
            .limit(BATCH).all())
    checked = healed = skipped = errors = 0
    from app.services.payment_registry import PaymentRegistry
    for p in rows:
        checked += 1
        try:
            if p.provider_config_id:
                provider = PaymentRegistry.get_by_id(p.provider_config_id)
            else:
                provider = PaymentRegistry.get_for_currency(p.currency)
            if not hasattr(provider, "fetch_order_payments"):
                skipped += 1
                continue
            attempts = provider.fetch_order_payments(p.provider_order_id)
            captured = next((a for a in attempts
                             if (a.get("status") or "") == "captured"), None)
            if captured is None:
                continue
            if captured.get("id") and not p.provider_payment_id:
                p.provider_payment_id = str(captured["id"])[:64]
            from app.services.payment_lifecycle import (
                activate_subscription_for_payment,
            )
            activate_subscription_for_payment(db, p,
                                              captured_via="reconcile")
            healed += 1
            log.info("reconcile.healed", payment_id=p.id,
                     order_id=p.provider_order_id,
                     gateway_payment_id=captured.get("id"))
        except Exception as e:
            errors += 1
            db.rollback()
            log.warning("reconcile.row_failed", payment_id=p.id,
                        error=str(e))
    if checked:
        log.info("reconcile.sweep_done", checked=checked, healed=healed,
                 skipped=skipped, errors=errors)
    return {"checked": checked, "healed": healed,
            "skipped": skipped, "errors": errors}


def register(scheduler) -> None:
    """Hourly job on the shared AsyncIOScheduler (idempotent id)."""
    def _tick() -> None:
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            reconcile_created_payments(db)
        except Exception as e:  # pragma: no cover - defensive
            log.error("reconcile.tick_failed", error=str(e))
        finally:
            db.close()

    scheduler.add_job(_tick, "interval", hours=1,
                      id="payments:reconcile", replace_existing=True)
    log.info("reconcile.job_registered")
