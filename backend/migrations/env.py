"""Alembic environment.

Wires the migration runner to the SQLAlchemy models in app.* so
`alembic revision --autogenerate` and `alembic upgrade head` work without
duplicating the connection string anywhere.

The DATABASE_URL comes from app.core.config (which reads backend/.env or
container env vars), so the same `alembic` invocation works locally,
in Docker, and in production.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the app importable regardless of where alembic is invoked from.
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings  # noqa: E402
from app.core.database import Base    # noqa: E402

# Trigger model registration so autogenerate sees every table.
import app.models  # noqa: E402, F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it. Useful for review."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
        compare_type=True, compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live database.

    ``transaction_per_migration=True`` is critical for Postgres enum
    work. Without it, alembic wraps EVERY pending migration in a single
    outer transaction — so a migration that does
    ``ALTER TYPE foo ADD VALUE 'bar'`` followed by another migration
    that ``UPDATE … SET col = 'bar'::foo`` both run before COMMIT, and
    Postgres rejects the second with::

        psycopg2.errors.UnsafeNewEnumValueUsage:
          unsafe use of new value "bar" of enum type foo
        HINT: New enum values must be committed before they can be used.

    Bit us on 2026-05-13 with migrations 0016 + 0017 (LeadSource
    values_callable refactor). The CI ``alembic upgrade head from empty
    DB`` gate passed by luck — empty ``leads`` table meant the UPDATE
    matched zero rows so Postgres never had to actually resolve the new
    enum value. Prod had rows; prod failed.

    With per-migration transactions, 0016 commits BEFORE 0017 starts,
    the new values become visible, and 0017's UPDATE works.

    Trade-off: each migration is its own atomic unit; a multi-step
    migration that wants atomicity across its own steps still gets it
    (the `upgrade()` body remains a single transaction). What changes
    is that two separate migrations no longer share a transaction —
    which is exactly what we want for the enum case, and a sound default
    for migration design in general (each migration should be
    independently safe to roll forward).
    """
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = settings.DATABASE_URL
    connectable = engine_from_config(cfg, prefix="sqlalchemy.",
                                     poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            compare_type=True, compare_server_default=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
