"""v5.2: rag_chunks table for RAG retrieval (pgvector-backed).

Adds the RAG infrastructure that powers the AI assistant's grounded
answers. Every retrievable piece of text — FAQ entries, plan
descriptions, question explanations, admin-uploaded documents — gets
a row here with its embedding vector for cosine-similarity search.

Design notes worth keeping in mind for future scope:

  • `tenant_id` is included but defaulted NULL. Reserved for future
    multi-tenant SaaS. Today everything belongs to "the default tenant"
    (NULL). When we extract this as a SaaS product, every tenant gets a
    UUID here and queries filter by it.

  • `provider` + `model` columns are stored on every row, NOT looked up
    from a global setting. Why: if the operator swaps embedding models,
    the OLD vectors are no longer comparable with NEW queries (different
    embedding space). Recording per-row lets us cleanly partition stale
    rows and migrate progressively instead of all-at-once.

  • `source_type` + `source_id` is a free-form polymorphic pointer
    (not a real FK to avoid table coupling). Today's source_types:
    'faq', 'plan', 'question_explanation', 'upload' (Day 2).
    Adding a new source = no schema change.

  • `source_version` lets us track when a chunk's content was last
    re-embedded. CRUD hooks bump this when the underlying row changes,
    so we can run a "reindex stale chunks" sweep without scanning
    everything.

  • Embedding column is `vector(1536)` — the dimension of OpenAI's
    `text-embedding-3-small`. If a future model uses a different dim,
    we'll add a second column (`embedding_3072` etc.) rather than
    re-typing — keeps backward-compat for any rows that haven't been
    re-embedded yet.

  • HNSW index on the embedding column with cosine distance. HNSW
    trades a little index-build time for fast ANN queries — right
    choice for read-heavy retrieval.

Forward-only, additive. No existing rows touched.

Revision ID: 0009_rag_chunks
Revises: 0008_question_type
"""
from alembic import op


revision = "0009_rag_chunks"
down_revision = "0008_question_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The pgvector image (pgvector/pgvector:pg16) ships the extension —
    # this just registers it inside our specific database. Idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id              SERIAL PRIMARY KEY,
            tenant_id       UUID,
            source_type     VARCHAR(32) NOT NULL,
            source_id       VARCHAR(120) NOT NULL,
            source_version  INTEGER NOT NULL DEFAULT 1,
            chunk_index     INTEGER NOT NULL DEFAULT 0,
            content         TEXT NOT NULL,
            content_tokens  INTEGER,
            provider        VARCHAR(64) NOT NULL,
            model           VARCHAR(128) NOT NULL,
            embedding       vector(1536) NOT NULL,
            metadata        JSONB DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_rag_chunk_source_index
                UNIQUE (tenant_id, source_type, source_id, chunk_index)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_rag_chunks_source
        ON rag_chunks (source_type, source_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_rag_chunks_tenant
        ON rag_chunks (tenant_id)
    """)
    # HNSW index for fast cosine-similarity ANN search. The default
    # parameters (m=16, ef_construction=64) are fine for our corpus
    # size; tune later if recall@k stops being satisfactory.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_cosine
        ON rag_chunks USING hnsw (embedding vector_cosine_ops)
    """)


def downgrade() -> None:
    raise NotImplementedError(
        "0009 is forward-only — the rag_chunks table holds the RAG corpus, "
        "dropping it would require a full re-embed run to restore "
        "(costly + slow). If absolutely needed, drop manually and "
        "re-create from source via the reindex endpoint."
    )
