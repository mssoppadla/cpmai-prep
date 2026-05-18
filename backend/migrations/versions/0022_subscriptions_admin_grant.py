"""v5.7: admin manual plan-grant support on subscriptions.

Six new columns on ``subscriptions`` that let an admin manually
grant / extend / revoke a paid plan on a user's behalf. This unblocks
the recurring support scenario where a payment got debited from the
user but the gateway (e.g. PayPal) held the funds in PENDING — our
system never receives a successful capture event, so the user shows
"no active subscription" despite having paid.

New columns (all NULLABLE — existing rows stay valid):

  * ``source``              — provenance tag. Values used by application
                              code: 'paid' (default for new paid subs),
                              'manual_admin_grant' (admin used the
                              grant UI), 'comp' (free comp), or
                              'refund_reversed'. NULL on rows
                              pre-dating this migration is treated as
                              'paid' by the read path.

  * ``granted_by``          — FK → users.id of the admin who granted.
                              NULL for organic 'paid' rows.

  * ``grant_reason``        — operator's free-text reason at grant
                              time. Captured for audit trail; not
                              shown to the end user.

  * ``revoked_at``          — when (and if) an admin revoked this sub
                              (typically because a refund was issued
                              after the fact). Once set, the paywall
                              treats the row as inactive regardless
                              of expires_at.

  * ``revoked_by``          — FK → users.id of the admin who revoked.

  * ``revoke_reason``       — free-text reason at revoke time.

Why all-nullable: keeps the migration trivially safe on both Postgres
(prod) and SQLite (test). Application code treats ``source IS NULL``
as 'paid' on the read path and always sets ``source`` on the write
path, so the operational invariants hold without a NOT NULL constraint
at the DB level.

Why NOT a separate ``subscription_audit`` table: the audit_logs table
is the universal event sink (architecture-overview.md §3). Every grant
/ revoke / extend writes an ``admin.subscription.*`` row there with
``metadata_json`` including the actor, the user, the plan, and the
reason. That keeps the data model lean and the operator dashboards
consistent.

Paywall semantics after this change (unchanged externally; just made
explicit here):

    is_active(sub) := sub.status == 'active'
                  AND (sub.expires_at IS NULL OR sub.expires_at > now())
                  AND sub.revoked_at IS NULL

The third clause is the only new bit; existing readers that don't
inspect ``revoked_at`` still work — they just don't honour revocations.
Callers we update in the same PR.

Revision ID: 0022_subscriptions_admin_grant
Revises: 0021_flagged_turn_resolved
"""
from alembic import op
import sqlalchemy as sa


revision = "0022_subscriptions_admin_grant"
down_revision = "0021_flagged_turn_resolved"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("source", sa.String(32), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("granted_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("grant_reason", sa.Text, nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("revoked_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("revoke_reason", sa.Text, nullable=True),
    )
    # The most common write is "list the user's current+historical subs"
    # for the admin's grant UI; we already have user_id indexed, so no
    # new index is strictly necessary. revoked_at IS NULL is a hot
    # filter on the paywall path — index it for the active-sub check.
    op.create_index(
        "ix_subscriptions_revoked_at",
        "subscriptions", ["revoked_at"],
    )


def downgrade() -> None:
    # Data-preservation contract: downgrades are forward-only. Use the
    # /admin/subscriptions endpoints to reverse a grant; don't drop
    # the columns and lose the audit trail.
    raise NotImplementedError(
        "0022_subscriptions_admin_grant: downgrade is intentionally "
        "unimplemented per the additive-only migration policy. "
        "Reverse a specific grant via /admin/subscriptions/{id}/revoke.")
