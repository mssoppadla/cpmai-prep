"""RAG chunk model — one row per retrievable piece of text.

Every embedded chunk in the corpus lands here: FAQ entries, plan
descriptions, question explanations, and (Day 2) admin-uploaded
documents. Retrieval is a cosine-similarity nearest-neighbour search
over the `embedding` column using a pgvector HNSW index.

The schema intentionally keeps `source_type`+`source_id` as a free-form
polymorphic pointer rather than a real FK — adding a new source type
(e.g. URL scrape, customer-uploaded PDF) is a one-line change, no
migration. The trade-off is that orphaned chunks can linger if a
source row is hard-deleted without going through the right reindex
hook; the reindex sweep handles this idempotently.

Forward-scope notes:
  - `tenant_id` is present but defaulted to NULL for the current
    single-tenant deployment. Future SaaS multi-tenancy adds a
    `WHERE tenant_id = :t` filter to every query — schema is already
    ready.
  - `provider` + `model` are stored per row so swapping embedding
    models doesn't immediately invalidate existing chunks; the
    retrieval layer can filter to a compatible (provider, model) set
    during a migration window.

Vector column typing:
  Postgres prod uses pgvector — column type is `vector(1536)`.
  SQLite tests have no pgvector — pgvector.sqlalchemy.Vector falls
  through to ARRAY/JSON which is fine for unit testing (we mock
  retrieval there anyway).
"""
from sqlalchemy import (
    Column, Integer, String, Text, JSON, DateTime, UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

# pgvector is an optional dep — keep the import safe so non-pg test
# environments don't crash on model registration. The actual column
# type only matters when binding to a real pgvector-equipped DB.
try:
    from pgvector.sqlalchemy import Vector
    _VECTOR_COLUMN = Vector(1536)
except Exception:                                       # pragma: no cover
    # SQLite / unit-test fallback: JSON column. Retrieval is mocked in
    # tests; nothing here actually runs the similarity operator.
    _VECTOR_COLUMN = JSON


class RagChunk(Base):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_type", "source_id", "chunk_index",
            name="uq_rag_chunk_source_index",
        ),
        Index("ix_rag_chunks_source", "source_type", "source_id"),
        Index("ix_rag_chunks_tenant", "tenant_id"),
    )

    id              = Column(Integer, primary_key=True)
    # Reserved for future multi-tenant SaaS; NULL today.
    tenant_id       = Column(UUID(as_uuid=True), nullable=True)

    # Polymorphic source pointer. Today's values: faq | plan |
    # question_explanation | upload (Day 2).
    source_type     = Column(String(32), nullable=False)
    source_id       = Column(String(120), nullable=False)
    # Bumped when the underlying source row is re-embedded. Lets a
    # "reindex stale rows" sweep find what's outdated.
    source_version  = Column(Integer, nullable=False, default=1)

    # For long documents that split into multiple chunks; 0 for
    # single-chunk sources.
    chunk_index     = Column(Integer, nullable=False, default=0)

    # The text that was embedded. We store it back here so retrieval
    # doesn't need a second roundtrip to fetch the original source.
    content         = Column(Text, nullable=False)
    content_tokens  = Column(Integer)

    # Per-row record of which model produced this vector. If the
    # operator swaps embedding models, we don't auto-invalidate —
    # retrieval can filter to the active model during migration.
    provider        = Column(String(64), nullable=False)
    model           = Column(String(128), nullable=False)

    embedding       = Column(_VECTOR_COLUMN, nullable=False)

    # Free-form structured data — caller-defined. Useful for filters
    # ("only chunks tagged difficulty=hard") and for surfacing source
    # info in citations.
    chunk_metadata  = Column("metadata", JSON, default=dict)

    created_at      = Column(DateTime(timezone=True),
                             server_default=func.now())
    updated_at      = Column(DateTime(timezone=True),
                             server_default=func.now(), onupdate=func.now())
