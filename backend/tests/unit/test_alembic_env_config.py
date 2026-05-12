"""Pins the alembic env.py configuration invariants.

Two things this test guards:

1. ``transaction_per_migration=True`` must be set on the online
   ``context.configure()`` call. Removing it re-introduces the
   2026-05-13 incident where two consecutive migrations that touched
   a Postgres enum (``ALTER TYPE leadsource ADD VALUE …`` in 0016
   followed by ``UPDATE leads SET source = lower(...)::leadsource`` in
   0017) failed mid-deploy with
   ``psycopg2.errors.UnsafeNewEnumValueUsage``. Auto-rollback caught
   it that time; we don't want to rely on auto-rollback.

2. Source code references to the lesson stay close to the call site
   so the next developer who reads env.py understands why the kwarg is
   there before deleting it.

This is a grep-style test — fast, no DB, no alembic invocation. The
behavioral assertion lives in ``migrations/env.py``'s docstring and the
production fix is the kwarg itself.

Why not a full migration-execution test: the repo's ``0001_baseline.py``
is intentionally a no-op (the schema was originally built via
``Base.metadata.create_all()`` then stamped — see
``vps-deployment-lessons.md`` row #23). So ``alembic upgrade head``
from an empty DB cannot succeed regardless of whether
transaction_per_migration is set — 0003 fails on a missing
``users`` table. A previous attempt to add that as a CI gate
(in this same PR's history) blocked every deploy. This static check
catches the only invariant we actually need.
"""
from pathlib import Path


ENV_PATH = (Path(__file__).resolve()
                .parent.parent.parent / "migrations" / "env.py")


def test_env_py_exists():
    """Smoke check the path resolution works — if this fails the rest
    of the suite produces a confusing FileNotFoundError."""
    assert ENV_PATH.exists(), f"alembic env.py not at {ENV_PATH}"


def test_env_sets_transaction_per_migration_true():
    """The exact regression guard. With this kwarg missing or set to
    False, ``alembic upgrade head`` wraps every pending migration in
    one transaction — which crashes any chain that does
    ``ALTER TYPE ... ADD VALUE`` in migration N and uses the new value
    in migration N+1's DML.

    The 2026-05-13 prod incident hit exactly that shape with
    LeadSource migrations 0016 + 0017. See ``migrations/env.py``
    docstring + ``docs/vps-deployment-lessons.md`` row 26c.
    """
    src = ENV_PATH.read_text(encoding="utf-8")
    assert "transaction_per_migration=True" in src, (
        "Alembic env.py must set transaction_per_migration=True. "
        "Removing it re-introduces the 2026-05-13 enum-in-same-"
        "transaction bug (UnsafeNewEnumValueUsage). See env.py "
        "docstring + lessons row 26c."
    )


def test_env_lesson_pointer_in_docstring():
    """Soft guard — the docstring near the configure() call should
    explain WHY transaction_per_migration is set. Without context, a
    well-meaning refactor in 6 months is likely to delete it as 'an
    odd default override.'"""
    src = ENV_PATH.read_text(encoding="utf-8")
    assert "UnsafeNewEnumValueUsage" in src, (
        "env.py should mention UnsafeNewEnumValueUsage so the next "
        "person reading the code understands the kwarg's purpose."
    )
