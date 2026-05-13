"""v5.10: GeoIP enrichment + system_settings.is_secret flag.

Pure ADD-COLUMN migration. Seven additive changes, all backward-
compatible (existing rows stay valid, existing reads keep working):

  1. ``system_settings.is_secret BOOLEAN NOT NULL DEFAULT FALSE`` —
     marks a row as containing a secret value. The /admin/settings GET
     endpoint masks the value for ``is_secret=true`` rows
     (``"••••last4"``); PATCH still accepts plaintext.
     Existing rows default to FALSE, which is the safe choice.

  2. ``leads.country VARCHAR(2)`` — ISO-3166-1 alpha-2 country code
     (e.g. ``IN``, ``SG``, ``AE``). Nullable because (a) historical rows
     pre-date GeoIP, and (b) any lookup failure (private IP, missing
     mmdb, MaxMind miss) falls back to NULL — never blocks the insert.

  3. ``leads.city VARCHAR(120)`` — best-effort city name from the
     MaxMind GeoLite2-City database. Nullable for the same reasons as
     ``country``. 120 chars is generous (longest English MaxMind city
     name is ~80 chars; we leave headroom for transliteration variants).

  4. ``users.country VARCHAR(2)`` — country at signup time. Snapshot
     semantics: this is "where the account was created", not "where
     the user is right now". Combined with ``last_login_country`` it
     gives admin analytics two slices: cohort geography (created here)
     vs. current geography (logging in from here).

  5. ``users.city VARCHAR(120)`` — city at signup time.

  6. ``users.last_login_ip VARCHAR(45)`` — IP of the most recent login.
     45 chars accommodates the longest IPv6 string form (39 chars) plus
     a small safety margin. Updated by every successful login (password
     or Google). Useful for security forensics and the admin "where is
     this user logging in from" tooltip.

  7. ``users.last_login_country VARCHAR(2)`` — country of the most
     recent login. Resolved from ``last_login_ip`` via the GeoIP
     lookup. Updated on every login, fail-open on lookup miss.

Why all in one migration: they ship together as the PR-A feature set
(GeoIP enrichment + admin-configurable refresh schedule). Splitting
would create transient half-feature states. All seven are pure ADD
COLUMN, so PostgreSQL takes the metadata lock once and no rewrites
are performed.

Note on ``transaction_per_migration``: enabled in env.py (see
2026-05-13 incident — alembic env config test pins this). This
migration is single-statement-equivalent and would be safe either way,
but the kwarg is what makes future ALTER TYPE chains safe; do NOT
remove it.

Revision ID: 0019_geoip_and_secret_flag
Revises: 0018_leads_score_column
"""
from alembic import op


revision = "0019_geoip_and_secret_flag"
down_revision = "0018_leads_score_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # system_settings.is_secret — defaults to FALSE for existing rows.
    # NOT NULL is safe because the DEFAULT applies to every existing row
    # in a single backfill (Postgres 11+ uses fast-path metadata only).
    op.execute("""
        ALTER TABLE system_settings
        ADD COLUMN IF NOT EXISTS is_secret BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # leads.country — ISO-3166-1 alpha-2 (always 2 chars when set).
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS country VARCHAR(2)
    """)

    # leads.city — MaxMind's English city name, transliterated.
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS city VARCHAR(120)
    """)

    # users.country / users.city — set at signup time, snapshot semantics.
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS country VARCHAR(2)
    """)
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS city VARCHAR(120)
    """)

    # users.last_login_ip — most-recent login IP. 45 chars fits IPv6 max
    # (39 chars) with safety margin. Useful for security forensics.
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS last_login_ip VARCHAR(45)
    """)

    # users.last_login_country — most-recent login country (resolved from
    # last_login_ip). Separate from users.country so admin analytics can
    # distinguish "user originally from IN" vs. "user currently logging in
    # from SG" (e.g. they moved).
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS last_login_country VARCHAR(2)
    """)


def downgrade() -> None:
    # Forward-only. Dropping is_secret would un-mask plaintext in the
    # /admin/settings GET response — a meaningful regression. Dropping
    # country/city would lose admin-visible enrichment that operators
    # may already be using to triage leads or for cohort analytics.
    # If you genuinely need to roll back, do it via a new forward
    # migration.
    raise NotImplementedError(
        "0019 is forward-only. Roll back via a new migration that "
        "explicitly addresses why the columns should disappear."
    )
