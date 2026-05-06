"""v1-v3 schema baseline.

Stub for the in-place schema that early dev environments built via
Base.metadata.create_all(). New DBs run `python seeds/bootstrap_schema.py`
or `Base.metadata.create_all()` from the bootstrap script before
alembic kicks in, then are stamped to head.

Future migrations should be true alembic revisions on top of this.

Revision ID: 0001_baseline
"""

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op: the baseline schema is created by SQLAlchemy from the
    # canonical model definitions. Bootstrapping is handled outside of
    # alembic for this revision; subsequent revisions are real ALTERs.
    pass


def downgrade() -> None:
    raise NotImplementedError("Cannot downgrade past the baseline.")
