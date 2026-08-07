"""Pause-on-leave exam timer + explicit auto-submit flag.

The exam clock now measures TIME ON SCREEN, not wall time since start:
- `remaining_seconds` — authoritative active-time budget left. Charged
  on each activity event (heartbeat / answer save / pause beacon),
  capped per gap so a lost beacon (crash, power cut) can't bill the
  hours the candidate was away.
- `last_activity_at` — when the budget was last charged.
- `auto_submitted` — explicit flag replacing the old
  `submitted_at >= expires_at` heuristic, set by every clock-driven
  finalization path so the UI can label "Auto-submitted — time expired"
  without timestamp archaeology.

Additive-only DDL + two idempotent backfills:
- in-progress rows get their current remaining wall-clock time so
  pre-pause drafts convert without losing whatever time they had left
  (rows already past their deadline get 0 → swept as before);
- submitted rows get auto_submitted per the old heuristic so history
  labels don't change retroactively.

Revision ID: 0046_pause_timer
Revises: 0045_error_logs

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa

revision = "0046_pause_timer"
down_revision = "0045_error_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("exam_sessions",
                  sa.Column("remaining_seconds", sa.Integer(), nullable=True))
    op.add_column("exam_sessions",
                  sa.Column("last_activity_at", sa.DateTime(timezone=True),
                            nullable=True))
    op.add_column("exam_sessions",
                  sa.Column("auto_submitted", sa.Boolean(), nullable=False,
                            server_default=sa.false()))
    # Convert live drafts: whatever wall-clock time they have left
    # becomes their active-time budget (floor 0 — already-expired rows
    # stay expired and get swept by the existing lazy paths).
    op.execute("""
        UPDATE exam_sessions
           SET remaining_seconds = GREATEST(
                   0, CAST(EXTRACT(EPOCH FROM (expires_at - NOW())) AS INTEGER)),
               last_activity_at = NOW()
         WHERE status = 'in_progress' AND remaining_seconds IS NULL
    """)
    # Preserve existing history labels under the old heuristic.
    op.execute("""
        UPDATE exam_sessions
           SET auto_submitted = TRUE
         WHERE status = 'submitted'
           AND submitted_at IS NOT NULL
           AND expires_at IS NOT NULL
           AND submitted_at >= expires_at
    """)
    # ── Duplicate-draft cleanup + guard ────────────────────────────────
    # Concurrent /start calls (double-click, a retried request, React's
    # double-invoked effects in dev) both saw "no draft" and both
    # inserted — so one candidate accumulated several in-progress
    # sittings per set, each later auto-submitting as a 0% row (the
    # 2026-08-07 flood). Keep the newest draft per (owner, set, domain),
    # delete the empty older ones, and let the partial unique index stop
    # the race at the database.
    op.execute("""
        DELETE FROM exam_sessions s
         WHERE s.status = 'in_progress'
           AND EXISTS (
               SELECT 1 FROM exam_sessions n
                WHERE n.status = 'in_progress'
                  AND n.id > s.id
                  AND n.exam_set_id = s.exam_set_id
                  AND n.practice_domain IS NOT DISTINCT FROM s.practice_domain
                  AND n.user_id IS NOT DISTINCT FROM s.user_id
                  AND n.anon_token IS NOT DISTINCT FROM s.anon_token)
           AND NOT EXISTS (
               SELECT 1 FROM exam_attempt_answers a
                WHERE a.exam_session_id = s.id
                  AND (a.selected_letter IS NOT NULL
                       OR a.selected_letters IS NOT NULL))
    """)
    # Any older duplicate that DID have answers is preserved as history
    # rather than deleted — finalize it so the index below can be built.
    op.execute("""
        UPDATE exam_sessions s
           SET status = 'submitted', auto_submitted = TRUE,
               submitted_at = COALESCE(s.last_activity_at, s.expires_at, NOW())
         WHERE s.status = 'in_progress'
           AND EXISTS (
               SELECT 1 FROM exam_sessions n
                WHERE n.status = 'in_progress'
                  AND n.id > s.id
                  AND n.exam_set_id = s.exam_set_id
                  AND n.practice_domain IS NOT DISTINCT FROM s.practice_domain
                  AND n.user_id IS NOT DISTINCT FROM s.user_id
                  AND n.anon_token IS NOT DISTINCT FROM s.anon_token)
    """)
    # One live draft per (user, set, domain) — enforced for signed-in
    # users; anonymous sittings are browser-bound and not deduped here.
    op.execute("""
        CREATE UNIQUE INDEX uq_one_live_draft_per_user_set
            ON exam_sessions (user_id, exam_set_id,
                              COALESCE(practice_domain, ''))
         WHERE status = 'in_progress' AND user_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_one_live_draft_per_user_set")
    op.drop_column("exam_sessions", "auto_submitted")
    op.drop_column("exam_sessions", "last_activity_at")
    op.drop_column("exam_sessions", "remaining_seconds")
