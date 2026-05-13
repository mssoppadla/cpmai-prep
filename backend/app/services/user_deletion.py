"""GDPR-compliant user soft-delete.

Both ``DELETE /users/me`` (self-service GDPR deletion) and
``DELETE /admin/users/{id}`` (admin-triggered junk-account cleanup)
go through this single service so the redaction contract stays
consistent across surfaces.

Why soft-delete, not hard-delete
--------------------------------
The User row is referenced as a foreign key by ~10 child tables —
``audit_logs``, ``leads.converted_user_id``, ``subscriptions``,
``payments``, ``journey_events``, ``assistant_logs``, ``exam_sessions``,
``system_settings.updated_by``, ``assistant_flagged_turns``, etc.

A hard ``DELETE FROM users WHERE id = X`` would either:
  (a) fail with an integrity error (current state — no model-level
      cascades are configured), or
  (b) succeed if cascades WERE configured, but at the cost of wiping
      audit history, payment records, and exam stats — which violates
      Indian tax-law retention (7 years on financial rows).

Soft-delete sidesteps both: the row stays in place, FKs hold, but the
PII is wiped and ``is_active = False`` so the account cannot log in or
appear in customer-facing surfaces.

The contract this enforces
--------------------------
After ``soft_delete_user(db, user)``:

* ``user.email`` → ``"deleted-{id}@redacted.invalid"``. RFC 2606 / 6761
  reserved domain — guaranteed never to be deliverable. The ``deleted-{id}``
  prefix keeps the row searchable in admin tools by ID without exposing
  the original address.
* ``user.name``, ``user.password_hash``, ``user.google_id`` → ``NULL``.
* ``user.is_active`` → ``False``. Combined with the auth deps'
  ``if not user.is_active`` checks, blocks login + token refresh + any
  authed endpoint.
* ``user.deleted_at`` → ``datetime.now(timezone.utc)``. Marker for
  "this row has been through the redaction flow"; idempotency check.

What this DOES NOT touch
------------------------
* ``payments`` / ``subscriptions`` — retained for tax compliance.
* ``exam_sessions`` — kept linked to the (now-redacted) user row so
  aggregate stats survive. No PII fields on the user row remain.
* ``assistant_logs`` — ``redacted_input`` was already PII-redacted at
  capture; ``response_preview`` is the model's reply (no user PII).
  Kept for product-analytics continuity.
* ``audit_logs`` — required for compliance / abuse investigation.

Idempotency
-----------
Calling on an already-deleted user is a no-op — returns ``False``
(meaning "no changes made"). Returns ``True`` if redaction was applied
on this call.
"""
from __future__ import annotations
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.user import User


def soft_delete_user(db: Session, user: User) -> bool:
    """Redact PII and mark the user inactive.

    Args:
        db: Active SQLAlchemy session. Will be committed.
        user: The user row to soft-delete. Modified in place.

    Returns:
        True if redaction was applied (user was active going in).
        False if the user was already soft-deleted (no-op).
    """
    if user.deleted_at is not None:
        return False

    user.email = f"deleted-{user.id}@redacted.invalid"
    user.name = None
    user.password_hash = None
    user.google_id = None
    user.is_active = False
    user.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return True
