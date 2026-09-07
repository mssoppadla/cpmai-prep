"""Storage-lifecycle tables backing /admin/storage.

``media_trash`` — a trashed upload. Trashing MOVES the file from its
original path into UPLOAD_ROOT/.trash/ (disk is only freed by
empty-trash), records who/when, and snapshots what the file was linked
to at that moment (``last_link_summary``). Restore re-checks links live
— the snapshot is display-only and never trusted for writes.

``media_candidates`` — a re-compressed copy of an existing upload,
produced by the browser encoder as a background job. A candidate NEVER
replaces its parent automatically: it stays ``pending`` until an admin
explicitly keeps it (lesson flips to the candidate, parent goes to
trash restorable) or discards it (candidate file deleted).
"""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.sql import func

from app.core.database import Base


class MediaTrash(Base):
    __tablename__ = "media_trash"

    id         = Column(Integer, primary_key=True)
    tenant_id  = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                        nullable=False, default=1, index=True)
    # The /uploads/... URL the file lived at before trashing — the path
    # a restore puts it back to (or a fresh uuid sibling on collision).
    original_path = Column(String(1024), nullable=False, index=True)
    # Where the bytes sit now, relative /uploads/.trash/... URL.
    trash_path    = Column(String(1024), nullable=False)
    size_bytes    = Column(BigInteger, nullable=False, default=0)
    mime          = Column(String(255))
    # JSON snapshot (list of link-ref dicts) of what referenced the file
    # when it was trashed. Display-only.
    last_link_summary = Column(Text)
    trashed_by  = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    trashed_at  = Column(DateTime(timezone=True),
                         server_default=func.now(), nullable=False)
    # Set when restored; restored rows stay for audit but leave the UI.
    restored_at = Column(DateTime(timezone=True))


class MediaCandidate(Base):
    __tablename__ = "media_candidates"

    id          = Column(Integer, primary_key=True)
    tenant_id   = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                         nullable=False, default=1, index=True)
    # /uploads/... URL of the original the candidate was encoded from.
    parent_path    = Column(String(1024), nullable=False, index=True)
    # /uploads/... URL of the compressed output.
    candidate_path = Column(String(1024), nullable=False)
    # The lesson whose video the parent serves (NULL if the parent was
    # not a lesson video when the job started).
    lesson_id   = Column(Integer, ForeignKey("lessons.id", ondelete="SET NULL"),
                         index=True)
    size_bytes        = Column(BigInteger, nullable=False, default=0)
    parent_size_bytes = Column(BigInteger, nullable=False, default=0)
    # pending → kept | discarded. Only pending rows show as candidates.
    status      = Column(String(16), nullable=False, default="pending",
                         index=True)
    created_at  = Column(DateTime(timezone=True),
                         server_default=func.now(), nullable=False)
    decided_at  = Column(DateTime(timezone=True))
    decided_by  = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
