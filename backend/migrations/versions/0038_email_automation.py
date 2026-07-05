"""Create ``email_automations`` + ``email_outbox`` for lifecycle email.

Contract: docs/contracts/email-automation.md

``email_automations`` — admin-defined mail types (trigger + conditions +
delay + content + attachments + send policy + per-type active toggle).
``email_outbox`` — durable send queue AND the per-user send history
(status/date/error/skip-reason) shown in the admin Activity tab.

Both tables carry ``tenant_id`` per contract I-1 (NOT NULL, DEFAULT 1,
FK tenants ON DELETE CASCADE, leading column of the hot-path indexes).

Additive (two new tables only) + fully reversible. No existing table or
row is touched. Seed rows for the four shipped mail types are inserted
by seeds/seed.py (idempotent), NOT by this migration, so re-seeding
follows the same discipline as default settings.

Revision ID: 0038_email_automation
Revises: 0037_lead_linkedin

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa


revision = "0038_email_automation"
down_revision = "0037_lead_linkedin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_automations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, server_default="1"),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("trigger_key", sa.String(length=64), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("delay_minutes", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("subject", sa.String(length=240), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("send_policy", sa.String(length=32), nullable=False,
                  server_default="once_per_user"),
        sa.Column("cooldown_days", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_email_automations_trigger_key",
                    "email_automations", ["trigger_key"])
    op.create_index("ix_email_automations_is_active",
                    "email_automations", ["is_active"])
    op.create_index("ix_email_automations_tenant_trigger",
                    "email_automations",
                    ["tenant_id", "trigger_key", "is_active"])

    op.create_table(
        "email_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, server_default="1"),
        sa.Column("automation_id", sa.Integer(),
                  sa.ForeignKey("email_automations.id",
                                ondelete="SET NULL"),
                  nullable=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("to_email", sa.String(length=255), nullable=False),
        sa.Column("dedup_key", sa.String(length=160), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True),
                  nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="pending"),
        sa.Column("source", sa.String(length=16), nullable=False,
                  server_default="automation"),
        sa.Column("attempts", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("skip_reason", sa.String(length=240), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_email_outbox_dedup_key",
                                "email_outbox", ["dedup_key"])
    op.create_index("ix_email_outbox_automation_id",
                    "email_outbox", ["automation_id"])
    op.create_index("ix_email_outbox_user_id", "email_outbox", ["user_id"])
    op.create_index("ix_email_outbox_status", "email_outbox", ["status"])
    op.create_index("ix_email_outbox_tenant_due",
                    "email_outbox", ["tenant_id", "status", "scheduled_at"])
    op.create_index("ix_email_outbox_user_created",
                    "email_outbox", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_email_outbox_user_created", table_name="email_outbox")
    op.drop_index("ix_email_outbox_tenant_due", table_name="email_outbox")
    op.drop_index("ix_email_outbox_status", table_name="email_outbox")
    op.drop_index("ix_email_outbox_user_id", table_name="email_outbox")
    op.drop_index("ix_email_outbox_automation_id",
                  table_name="email_outbox")
    op.drop_constraint("uq_email_outbox_dedup_key", "email_outbox",
                       type_="unique")
    op.drop_table("email_outbox")
    op.drop_index("ix_email_automations_tenant_trigger",
                  table_name="email_automations")
    op.drop_index("ix_email_automations_is_active",
                  table_name="email_automations")
    op.drop_index("ix_email_automations_trigger_key",
                  table_name="email_automations")
    op.drop_table("email_automations")
