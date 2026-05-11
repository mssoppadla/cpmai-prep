"""v5.4: add `chat_callback` value to LeadSource enum.

Backs the new "Talk to a human" link in the chat widget. When a signed-in
user submits the callback form, we insert a row into `leads` tagged with
this source so the admin sees it alongside other contact requests in
/admin/leads.

Postgres enums need an explicit ALTER TYPE ... ADD VALUE; appending to
the Python enum alone won't work in prod.

Revision ID: 0012_lead_source_chat_callback
Revises: 0011_rag_documents
"""
from alembic import op


revision = "0012_lead_source_chat_callback"
down_revision = "0011_rag_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS guards against re-running on an already-upgraded DB.
    # Available since Postgres 12.
    op.execute("ALTER TYPE leadsource ADD VALUE IF NOT EXISTS 'chat_callback'")


def downgrade() -> None:
    raise NotImplementedError(
        "0012 is forward-only — Postgres has no DROP VALUE for enums "
        "without a destructive type-rebuild that would risk data loss."
    )
