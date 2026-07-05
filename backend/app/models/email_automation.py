"""Admin-extensible lifecycle email automation (mail types + outbox).

Contract: docs/contracts/email-automation.md

``EmailAutomation`` — one row per admin-defined mail type:
    WHEN <trigger_key> IF <conditions> WAIT <delay_minutes>
    SEND <subject/html_body + attachments> per <send_policy>.

Admins create/edit these in /admin/email-automations. Adding a new mail
type is pure data — no code change. The trigger_key must be one of the
code-defined catalog in app/services/email/automation.py (new *events*
need instrumentation; everything built on them is config).

``EmailOutbox`` — the durable queue AND the per-user send history the
admin sees in the Activity tab. Rows are enqueued fail-soft at trigger
time and drained by the 60s dispatcher tick (app/services/email/
dispatcher.py). Statuses: pending → sent | skipped | failed | cancelled,
each with a timestamp and a reason/error so the admin always knows
whether a mail went out.

Deliberately separate from ``email_templates`` (the lead → auto-offer
flow): a lifecycle row must never be selectable by ``select_template()``
or shadow the lead default template.
"""
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index,
    JSON,
)
from sqlalchemy.sql import func
from app.core.database import Base


# Send-policy values (kept as strings, validated at the API boundary):
#   once_per_user   — one send ever per user+automation (dedup ref "once")
#   replace_pending — a new qualifying event replaces the pending row's
#                     schedule instead of adding another mail
#   every_event     — every event sends (optionally cooldown_days apart)
SEND_POLICIES = ("once_per_user", "replace_pending", "every_event")

OUTBOX_STATUSES = ("pending", "sent", "skipped", "failed", "cancelled")


class EmailAutomation(Base):
    __tablename__ = "email_automations"
    __table_args__ = (
        Index("ix_email_automations_tenant_trigger",
              "tenant_id", "trigger_key", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    # Contract I-1: every new table is tenant-scoped.
    tenant_id = Column(Integer,
                       ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, server_default="1")
    # Admin-facing label, e.g. "Welcome — signup without payment".
    name = Column(String(160), nullable=False)
    # One of automation.TRIGGERS. Unknown values (e.g. a trigger removed
    # in a future release) are skipped at dispatch with a WARN, never an
    # error — see contract §3.
    trigger_key = Column(String(64), nullable=False, index=True)
    # JSON list of {"type": ..., ...params} predicates — see
    # automation.evaluate_conditions(). Empty list = always matches.
    conditions = Column(JSON, nullable=False, default=list)
    # Wait between trigger and send. UI presents days/hours/minutes;
    # storage is always minutes. For payment.abandoned this doubles as
    # the "stuck in created for N minutes" threshold.
    delay_minutes = Column(Integer, nullable=False, default=0)
    subject = Column(String(240), nullable=False)
    html_body = Column(Text, nullable=False)
    # JSON list of {url, filename, mime_type, size_bytes} exactly as the
    # /admin/uploads endpoint returns them. Total size capped at save
    # time (15MB); paths re-validated under UPLOAD_ROOT at send time.
    attachments = Column(JSON, nullable=False, default=list)
    send_policy = Column(String(32), nullable=False,
                         default="once_per_user")
    # every_event only: suppress a send if one was SENT within N days.
    cooldown_days = Column(Integer, nullable=False, default=0)
    # Per-mail-type admin toggle (R6). Checked at dispatch time too, so
    # flipping OFF also stops already-queued rows (they become skipped).
    is_active = Column(Boolean, nullable=False, default=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    __table_args__ = (
        # Dispatcher hot path: due pending rows for this tenant.
        Index("ix_email_outbox_tenant_due",
              "tenant_id", "status", "scheduled_at"),
        # Activity tab: newest first, filterable by user.
        Index("ix_email_outbox_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer,
                       ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, server_default="1")
    # SET NULL so history survives an automation delete — the Activity
    # tab keeps showing what was sent (name snapshotted in context).
    automation_id = Column(Integer,
                           ForeignKey("email_automations.id",
                                      ondelete="SET NULL"),
                           nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    to_email = Column(String(255), nullable=False)
    # Duplicate-send guard — see automation.build_dedup_key() for the
    # per-policy format. Unique index makes double-enqueue a no-op.
    dedup_key = Column(String(160), nullable=False, unique=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(16), nullable=False, default="pending",
                    index=True)
    # 'automation' = trigger-driven; 'manual' = admin bulk send from the
    # Users page (conditions not applied, personalization still is).
    source = Column(String(16), nullable=False, default="automation")
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text)          # failures: actual SMTP/render error
    skip_reason = Column(String(240))  # skips: why the send was withheld
    sent_at = Column(DateTime(timezone=True))
    # Rendered-placeholder snapshot ({"name": "...", "plan_name": ...})
    # so the Activity tab can show exactly what the user received even
    # after the automation's template changes.
    context = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
