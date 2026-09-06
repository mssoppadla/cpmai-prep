"""enrollments.subscription_id FK + backfill from grant_reason.

Access-lifecycle fix (prod incident 2026-09-06): subscription-derived
enrollments had no structural link to the subscription that created
them — the sub id lived only inside the free-text grant_reason — so
revoking a subscription could not cascade to the access it granted.

Adds the nullable FK and backfills it for existing rows by parsing the
"Auto-enrolled via subscription #N" reason strings, joined against
subscriptions to guarantee FK validity. Rows whose reason doesn't parse
(or whose sub was deleted) stay NULL — the read-time revalidation
introduced alongside this migration covers them.

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa

revision = "0051_enrollment_sub_fk"
down_revision = "0050_anon_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enrollments",
        sa.Column("subscription_id", sa.Integer(),
                  sa.ForeignKey("subscriptions.id", ondelete="SET NULL"),
                  nullable=True),
    )
    op.create_index("ix_enrollments_subscription_id",
                    "enrollments", ["subscription_id"])
    # Backfill: parse "... subscription #<id> ..." out of grant_reason.
    # substring() returns NULL when the pattern doesn't match; the join
    # against subscriptions guarantees we never write a dangling FK.
    op.execute(sa.text(r"""
        UPDATE enrollments e
           SET subscription_id = s.id
          FROM subscriptions s
         WHERE e.source = 'subscription'
           AND e.subscription_id IS NULL
           AND s.id = NULLIF(substring(e.grant_reason
                                        from 'subscription #(\d+)'), '')::int
           AND s.user_id = e.user_id
    """))


def downgrade() -> None:
    op.drop_index("ix_enrollments_subscription_id", table_name="enrollments")
    op.drop_column("enrollments", "subscription_id")
