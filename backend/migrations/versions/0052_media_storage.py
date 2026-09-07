"""media_trash + media_candidates — storage lifecycle for /admin/storage.

Trash-not-delete: trashed uploads move (restorably) to .trash/ and the
row records where they were and what referenced them. Candidates are
re-compressed copies of existing uploads awaiting an explicit
keep/discard decision — never auto-swapped.

No guarded tables touched. Revision id stays under VARCHAR(32).
"""
from alembic import op
import sqlalchemy as sa

revision = "0052_media_storage"
down_revision = "0051_enrollment_sub_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_trash",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("original_path", sa.String(1024), nullable=False),
        sa.Column("trash_path", sa.String(1024), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("mime", sa.String(255)),
        sa.Column("last_link_summary", sa.Text()),
        sa.Column("trashed_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("trashed_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_media_trash_tenant_id", "media_trash", ["tenant_id"])
    op.create_index("ix_media_trash_original_path",
                    "media_trash", ["original_path"])

    op.create_table(
        "media_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("parent_path", sa.String(1024), nullable=False),
        sa.Column("candidate_path", sa.String(1024), nullable=False),
        sa.Column("lesson_id", sa.Integer(),
                  sa.ForeignKey("lessons.id", ondelete="SET NULL")),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("parent_size_bytes", sa.BigInteger(), nullable=False,
                  server_default="0"),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_index("ix_media_candidates_tenant_id",
                    "media_candidates", ["tenant_id"])
    op.create_index("ix_media_candidates_parent_path",
                    "media_candidates", ["parent_path"])
    op.create_index("ix_media_candidates_lesson_id",
                    "media_candidates", ["lesson_id"])
    op.create_index("ix_media_candidates_status",
                    "media_candidates", ["status"])


def downgrade() -> None:
    op.drop_table("media_candidates")
    op.drop_table("media_trash")
