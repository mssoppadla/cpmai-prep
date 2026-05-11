"""v5.4: rag_documents — admin-uploaded source files.

Adds a table to track files admins upload through the new
/admin/rag/upload endpoint. The actual chunked + embedded content
lives in rag_chunks with source_type='upload' and source_id pointing
at the rag_documents row's id; this table holds the file's metadata
(filename, content_type, size, uploader, status).

We do NOT store the raw file bytes — once the content is chunked and
embedded into rag_chunks, the file's job is done. If admin wants to
re-process a file they re-upload it. (Storing bytes on disk creates
backup + retention obligations we'd rather avoid for an MVP.)

Forward-only, additive. No existing rows touched.

Revision ID: 0011_rag_documents
Revises: 0010_user_daily_chat_override
"""
from alembic import op


revision = "0011_rag_documents"
down_revision = "0010_user_daily_chat_override"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS rag_documents (
            id              SERIAL PRIMARY KEY,
            tenant_id       UUID,
            filename        VARCHAR(255) NOT NULL,
            content_type    VARCHAR(64) NOT NULL,
            size_bytes      INTEGER NOT NULL,
            chunk_count     INTEGER NOT NULL DEFAULT 0,
            status          VARCHAR(32) NOT NULL DEFAULT 'ingested',
            created_by      INTEGER REFERENCES users(id),
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_rag_documents_created_by
        ON rag_documents (created_by)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_rag_documents_tenant
        ON rag_documents (tenant_id)
    """)


def downgrade() -> None:
    raise NotImplementedError(
        "0011 is forward-only — uploaded-doc audit history is preserved."
    )
