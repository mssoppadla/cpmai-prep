"""lessons.free_preview_seconds + preview_video_url — timed free preview.

Option 3 (chosen 2026-09): the admin sets how many seconds of a video
lesson visitors may sample, and generates a REAL clip of that length
with the in-browser encoder. Visitors are served only the clip
(preview_video_url) — the full video URL never leaves the server for
non-enrolled users. Both nullable; NULL preview_video_url falls back to
the pre-existing behavior (full video for is_free_preview lessons).
"""
from alembic import op
import sqlalchemy as sa

revision = "0053_free_preview_clip"
down_revision = "0052_media_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lessons",
                  sa.Column("free_preview_seconds", sa.Integer(), nullable=True))
    op.add_column("lessons",
                  sa.Column("preview_video_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("lessons", "preview_video_url")
    op.drop_column("lessons", "free_preview_seconds")
