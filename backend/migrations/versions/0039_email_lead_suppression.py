"""Lead recipients + suppression groups for email automations.

Contract: docs/contracts/email-automation.md (amended in this commit).

Two additive changes:

1. ``email_outbox`` learns to address LEADS (landing-form submitters who
   have no user account yet): ``user_id`` becomes nullable and a new
   nullable ``lead_id`` FK is added. Exactly one of the two is set —
   enforced in code (enqueue paths), not as a DB CHECK, mirroring how
   the codebase handles similar either-or columns (ExamSession
   user_id/anon_token).

2. ``email_automations.suppression_group`` — mail types sharing a group
   name suppress each other per RECIPIENT EMAIL: once any automation in
   the group has a ``sent`` outbox row for an address, the others skip
   (recorded as skipped + reason in the Activity feed). Email-based so
   it follows a person across the lead → signed-up-user transition.
   NULL/empty = no suppression.

Additive + fully reversible. The downgrade re-tightens
``email_outbox.user_id`` to NOT NULL, which requires lead-addressed
rows to be gone — it deletes them (they are meaningless without the
column). Acceptable: downgrade of a feature migration removes that
feature's data, and outbox rows are operational telemetry, not
financial records.

Revision ID: 0039_email_lead_suppress
Revises: 0038_email_automation

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa


revision = "0039_email_lead_suppress"
down_revision = "0038_email_automation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("email_outbox", "user_id",
                    existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "email_outbox",
        sa.Column("lead_id", sa.Integer(),
                  sa.ForeignKey("leads.id", ondelete="CASCADE"),
                  nullable=True),
    )
    op.create_index("ix_email_outbox_lead_id", "email_outbox", ["lead_id"])

    op.add_column(
        "email_automations",
        sa.Column("suppression_group", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_email_automations_suppression_group",
                    "email_automations", ["suppression_group"])


def downgrade() -> None:
    op.drop_index("ix_email_automations_suppression_group",
                  table_name="email_automations")
    op.drop_column("email_automations", "suppression_group")

    op.drop_index("ix_email_outbox_lead_id", table_name="email_outbox")
    # Lead-addressed rows have user_id NULL and cannot survive the
    # NOT NULL re-tightening below.
    op.execute("DELETE FROM email_outbox WHERE user_id IS NULL")
    op.drop_column("email_outbox", "lead_id")
    op.alter_column("email_outbox", "user_id",
                    existing_type=sa.Integer(), nullable=False)
