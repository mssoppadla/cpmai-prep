"""RagDocument — metadata for an admin-uploaded source file.

One row per file the admin uploads via /admin/rag/upload. The file's
chunked content lives in rag_chunks with source_type='upload' and
source_id = str(RagDocument.id). Deleting a RagDocument cascades a
manual cleanup of its rag_chunks rows (the admin endpoint handles it).

We deliberately do NOT store the raw bytes — once the content is
chunked + embedded, re-processing means re-uploading. Avoids backup
weight and a second source-of-truth.
"""
from sqlalchemy import (
    Column, Integer, String, ForeignKey, DateTime, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base


class RagDocument(Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        Index("ix_rag_documents_created_by", "created_by"),
        Index("ix_rag_documents_tenant", "tenant_id"),
    )

    id            = Column(Integer, primary_key=True)
    tenant_id     = Column(UUID(as_uuid=True), nullable=True)
    filename      = Column(String(255), nullable=False)
    content_type  = Column(String(64), nullable=False)
    size_bytes    = Column(Integer, nullable=False)
    chunk_count   = Column(Integer, nullable=False, default=0)
    # 'ingested' on success; future 'failed' / 'processing' if we go async.
    status        = Column(String(32), nullable=False, default="ingested")
    created_by    = Column(Integer, ForeignKey("users.id"))
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
