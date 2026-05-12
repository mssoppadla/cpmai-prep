"""v5.6: add CHAT_CALLBACK (uppercase) to leadsource enum.

Why this exists (a tale of enum naming):

The ``LeadSource`` enum in ``app/models/lead.py`` is declared like:

    class LeadSource(str, enum.Enum):
        LANDING_HERO   = "landing_hero"
        ...
        CHAT_CALLBACK  = "chat_callback"

And the column declaration is:

    source = Column(SQLEnum(LeadSource), nullable=False)

There's NO ``values_callable=`` — so SQLAlchemy uses the Python enum
**NAMES** when generating DDL AND when sending values to Postgres on
INSERT. So the original DDL (via ``Base.metadata.create_all()`` during
the first install) created the leadsource enum with values
``LANDING_HERO``, ``NEWSLETTER``, etc. — all uppercase NAMES.

When PR #21 added the chat-callback feature, migration
``0012_lead_source_chat_callback.py`` did:

    ALTER TYPE leadsource ADD VALUE IF NOT EXISTS 'chat_callback'

That added the lowercase **VALUE** instead of the uppercase **NAME**.
The migration succeeded but new inserts still failed: SQLAlchemy sent
``CHAT_CALLBACK`` (the NAME) but the enum only had ``chat_callback``.
``psycopg2.errors.InvalidTextRepresentation`` → 500 → bug.

This migration adds the correct uppercase value so SQLAlchemy's default
NAME-based serialization works. The lowercase ``chat_callback`` value
added by 0012 stays in the enum (Postgres has no ``ALTER TYPE …
DROP VALUE`` short of a destructive type-rebuild) — but it's unused
dead code at the Postgres level, harmless.

Long-term, the model SHOULD be refactored to use
``values_callable=lambda enum_cls: [e.value for e in enum_cls]`` (as
``QuestionType`` does in ``app/models/question.py``) so the on-disk
enum matches what an admin querying psql sees in lowercase
``column_type::leadsource`` casts. That refactor needs a data-migration
to translate every existing row's ``LANDING_HERO`` to ``landing_hero``,
which is out of scope here. Tracked in the backlog. For now, this
migration just makes the existing convention consistent.

Operational note: this migration is a no-op on a VPS that was already
hot-patched manually (run ``ALTER TYPE leadsource ADD VALUE IF NOT EXISTS
'CHAT_CALLBACK'`` to unblock prod). ``IF NOT EXISTS`` keeps it
idempotent in either order.

Revision ID: 0014_lead_source_chat_callback_name
Revises: 0013_users_deleted_at
"""
from alembic import op


revision = "0014_lead_source_chat_callback_name"
down_revision = "0013_users_deleted_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE leadsource ADD VALUE IF NOT EXISTS 'CHAT_CALLBACK'")


def downgrade() -> None:
    raise NotImplementedError(
        "0014 is forward-only — Postgres has no DROP VALUE for enums "
        "without a destructive type rebuild."
    )
