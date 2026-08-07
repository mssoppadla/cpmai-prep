"""Create error_logs — client/network error reports behind /admin/error-logs.

Browsers POST fetch failures (QUIC stalls, connection drops), HTTP 5xx
responses, and uncaught JS exceptions to /errors/report; admins read
windowed summaries on /admin/error-logs. Pure additive DDL — no
existing table is touched, so the CI bootstrap gate and prod deploy
path are unaffected.

Revision ID: 0045_error_logs
Revises: 0044_backfill_result_snapshot

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa

revision = "0045_error_logs"
down_revision = "0044_backfill_result_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "error_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("anon_id", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("path", sa.String(length=500), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_error_logs_user_id", "error_logs", ["user_id"])
    op.create_index("ix_error_logs_anon_id", "error_logs", ["anon_id"])
    op.create_index("ix_error_logs_source", "error_logs", ["source"])
    op.create_index("ix_error_logs_error_type", "error_logs", ["error_type"])
    op.create_index("ix_error_logs_created_at", "error_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("error_logs")
