"""User subscriptions.

A `Subscription` is the resolved access state for a user after a
successful payment for a `Plan`. We keep `plan` (string) for legacy
free-tier rows and as a denormalised display label; `plan_id` (FK) is
the new authoritative pointer that drives paywall checks.

`expires_at` is the time-bound field. Server sets it to
`paid_at + plan.duration_days` at verify time. The paywall treats a row
as active iff:

    status='active' AND (expires_at IS NULL OR expires_at > now())
                    AND revoked_at IS NULL

NULL `expires_at` means "no expiry" — used for legacy free-tier rows
only; new paid rows always have an expiry.

Admin manual-grant fields (migration 0022)
==========================================

These six columns let operators manually grant / extend / revoke a
sub on a user's behalf. Use case: a payment was debited at the
gateway but never marked successful in our system (e.g. PayPal
PENDING that never released, or a webhook we missed) — admin uses
the grant UI to unblock the user immediately. Every action also
writes an audit_logs row.

  * ``source``        — 'paid' | 'manual_admin_grant' | 'comp' |
                        'refund_reversed'. NULL pre-migration rows
                        are read as 'paid'.
  * ``granted_by``    — admin user_id (NULL for organic paid rows)
  * ``grant_reason``  — free-text operator note at grant time
  * ``revoked_at``    — when an admin revoked (e.g. post-refund);
                        once set, paywall treats row as inactive
                        regardless of expires_at
  * ``revoked_by``    — admin user_id who revoked
  * ``revoke_reason`` — free-text operator note at revoke time
"""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan = Column(String(32), nullable=False)            # legacy label: free | pro | …
    plan_id = Column(Integer, ForeignKey("plans.id"), index=True)
    status = Column(String(32), nullable=False)          # active | cancelled | expired
    current_period_start = Column(DateTime(timezone=True))
    current_period_end   = Column(DateTime(timezone=True))
    expires_at           = Column(DateTime(timezone=True), index=True)
    razorpay_subscription_id = Column(String(64))
    cancelled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())

    # Admin manual-grant + revoke columns (migration 0022). All NULLABLE
    # so existing 'paid' rows keep working unchanged. Application code
    # treats source IS NULL as 'paid' on the read path.
    source        = Column(String(32))
    granted_by    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    grant_reason  = Column(Text)
    revoked_at    = Column(DateTime(timezone=True), index=True)
    revoked_by    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    revoke_reason = Column(Text)

    @property
    def is_revoked(self) -> bool:
        """Convenience helper for the paywall check."""
        return self.revoked_at is not None

    @property
    def effective_source(self) -> str:
        """Source with NULL coerced to 'paid' (legacy-row sentinel)."""
        return self.source or "paid"
