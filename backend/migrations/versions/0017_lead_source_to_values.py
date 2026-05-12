"""v5.10: normalize existing leads.source rows to lowercase VALUES.

Pairs with the Lead.source column refactor that swaps it to use
``values_callable=lambda enum_cls: [e.value for e in enum_cls]``.

Every historical row stored its source as the Python enum NAME
(uppercase, e.g. ``LANDING_HERO``) — that's the default SQLAlchemy
behavior when no ``values_callable`` is set. After this migration the
model uses VALUES (lowercase, ``landing_hero``), and any leftover
uppercase row would 500 the admin /leads page on read because
``_value2member_map_`` only contains lowercase keys.

This is a single-statement migration. The trick:
``UPDATE leads SET source = lower(source::text)::leadsource``

  • ``source::text`` casts the current enum value to its string form
    (e.g. ``'LANDING_HERO'``).
  • ``lower(...)`` converts to ``'landing_hero'``.
  • ``::leadsource`` casts back to the enum type. The lowercase value
    must already exist in the enum — that's what 0016 ensures.

Runs in a separate transaction from 0016 because Postgres won't let
you use an enum value that was added earlier in the same transaction.
Alembic gives each migration its own transaction by default, so just
splitting into two files is enough.

Affects ``leads`` only. ``chat_callback`` rows (if any) lowercase to
themselves — no-op for those.

Revision ID: 0017_lead_source_to_values
Revises: 0016_lead_source_add_lower
"""
from alembic import op


revision = "0017_lead_source_to_values"
down_revision = "0016_lead_source_add_lower"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WHERE clause is a defensive guard so this is a true no-op if the
    # column is already all-lowercase (e.g. on a fresh-install DB that
    # never had any uppercase rows). It also makes the operation faster
    # on a populated table.
    op.execute("""
        UPDATE leads
           SET source = lower(source::text)::leadsource
         WHERE source::text <> lower(source::text)
    """)


def downgrade() -> None:
    raise NotImplementedError(
        "0017 is forward-only — the inverse (UPPER(...)) would silently "
        "lose the new chat_callback rows (no uppercase CHAT_CALLBACK in "
        "the Python enum). If a true rollback is ever needed, do it by "
        "hand with full data audit."
    )
