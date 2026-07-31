"""Canonicalize legacy `questions.domain` free-text to ECO codes.

Early bulk imports stored the sheet's domain cell verbatim when it
wasn't an exact code/name/slug — values like "D-I Trustworthy" or
"D-II Identify Business Needs and Solutions". Those rows split into
their own buckets on the results screen (grouping is by resolved
domain) and render as a blank dropdown in the question editor.

0033 deliberately skipped a backfill on the theory that read-time
resolution groups legacy text sensibly; the resolver has since been
taught these legacy spellings (app.core.domains.get), and this
migration converges the stored data to match, so SQL-level exact
matches (admin domain filter, editor dropdown, frontend canon maps)
agree with the Python resolver.

Data-only and idempotent: rewrites only values that resolve to a
canonical code, leaves genuinely unknown text untouched, touches no
schema. From an empty DB (CI migration-drift gate) it updates 0 rows.

Forward-only: downgrade is a no-op — the prior free-text spellings
are not worth reconstructing (they were never canonical), and the
rewritten values remain valid inputs to every reader old and new.

The resolver is inlined below (not imported from app.core.domains) so
the migration stays frozen even if the registry changes later.

Revision ID: 0042_canonical_question_domains
Revises: 0041_payment_utm

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "0042_canonical_question_domains"
down_revision = "0041_payment_utm"
branch_labels = None
depends_on = None


# Frozen copy of the ECO domain registry as of this revision.
_DOMAINS = (
    ("D-I",   "Trustworthy AI",                           "trustworthy-ai"),
    ("D-II",  "Identify Business Needs & Solutions",      "business-needs"),
    ("D-III", "Identify Data Needs",                      "data-needs"),
    ("D-IV",  "Manage AI Model Development & Evaluation", "model-dev-eval"),
    ("D-V",   "Model Operationalization",                 "operationalization"),
)
_CODES = {c for c, _, _ in _DOMAINS}

# Leading ECO-code shapes seen in legacy data: "D-I Trustworthy",
# "D I - Trustworthy AI", "D III -Identify Data Needs".
_CODE_PREFIX = re.compile(r"^d[\s\-–—.]*([ivx]+)\b", re.IGNORECASE)


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _resolve(raw: str) -> str | None:
    """Mirror of app.core.domains.get() at this revision: code, slug,
    name (case/punctuation/'&'-tolerant), or a leading ECO code as in
    'D-I Trustworthy' / 'D I - Trustworthy AI'. None when nothing
    matches."""
    key = raw.strip()
    if not key:
        return None
    if key in _CODES or key.upper() in _CODES:
        return key.upper()
    for code, name, slug in _DOMAINS:
        if key.lower() == slug or _norm(key) == _norm(name):
            return code
    m = _CODE_PREFIX.match(key)
    if m:
        code = f"D-{m.group(1).upper()}"
        return code if code in _CODES else None
    return None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT DISTINCT domain FROM questions "
        "WHERE domain IS NOT NULL AND domain <> ''"
    )).fetchall()
    for (stored,) in rows:
        code = _resolve(stored)
        if code and code != stored:
            bind.execute(
                sa.text("UPDATE questions SET domain = :code "
                        "WHERE domain = :stored"),
                {"code": code, "stored": stored},
            )


def downgrade() -> None:
    # Forward-only data fix (see module docstring) — nothing to restore.
    pass
