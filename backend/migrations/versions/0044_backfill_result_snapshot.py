"""Backfill result_snapshot for attempts submitted before 0043.

0043 added `exam_sessions.result_snapshot` (frozen review payload,
written at submit time by new code). Attempts submitted BEFORE that
deploy have no snapshot, so their reviews would keep tracking live
question edits forever. This migration derives a snapshot for each of
them from the data available at migration time: the attempt's stored
answers (selection + verdict — true history) joined to the questions
and options as they exist NOW (best available content — any edits made
before this migration are already irreversible).

Fidelity rule: the snapshot mirrors exactly what get_result's live
reconstruction shows today — answers whose question was deleted or
removed from the set are skipped (they are already invisible in the
current review; resurrecting them would CHANGE what the candidate
sees, not preserve it).

Runs BEFORE the app switches to snapshot-serving code (deploy.sh:
alembic upgrade head precedes the container swap), so every historical
attempt is frozen before any future question edit can alter it.

Data-only and idempotent (targets `result_snapshot IS NULL` only;
re-running touches nothing new). Zero rows on an empty DB, so the CI
bootstrap gate is unaffected. Forward-only: downgrade is a no-op —
backfilled snapshots are indistinguishable from submit-written ones,
and leaving them in place is harmless to older code (the column is
simply unread).

Enum storage note: `questions.difficulty` stores enum NAMES ("EASY" —
no values_callable on the column) while `question_type` stores VALUES
("single_choice"); the snapshot schema (QuestionResultView) expects
VALUES for both, hence the explicit difficulty mapping.

Revision ID: 0044_backfill_result_snapshot
Revises: 0043_attempt_result_snapshot

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0044_backfill_result_snapshot"
down_revision = "0043_attempt_result_snapshot"
branch_labels = None
depends_on = None


_DIFFICULTY_VALUES = {"EASY": "easy", "MEDIUM": "medium", "HARD": "hard"}

_sessions_t = sa.table(
    "exam_sessions",
    sa.column("id", sa.Integer),
    sa.column("result_snapshot", sa.JSON),
)


def _as_list(v):
    """JSON columns come back as parsed lists on Postgres but raw text
    on SQLite when read via textual SQL — accept both."""
    if v is None:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return []
    return list(v) if isinstance(v, (list, tuple)) else []


def _set_questions(bind, exam_set_id, cache):
    """{question_id: (question_row, [option_rows])} for one set, cached
    across sessions of the same set."""
    if exam_set_id in cache:
        return cache[exam_set_id]
    qmap = {}
    rows = bind.execute(sa.text(
        "SELECT q.id, q.stem, q.topic_id, q.domain, q.task, q.enablers, "
        "       q.remarks, q.difficulty, q.question_type, q.explanation "
        "FROM questions q "
        "JOIN exam_set_questions esq ON esq.question_id = q.id "
        "WHERE esq.exam_set_id = :es"), {"es": exam_set_id}).fetchall()
    for row in rows:
        opts = bind.execute(sa.text(
            "SELECT option_letter, text, is_correct, reasoning "
            "FROM question_options WHERE question_id = :qid "
            "ORDER BY option_letter"), {"qid": row[0]}).fetchall()
        qmap[row[0]] = (row, opts)
    cache[exam_set_id] = qmap
    return qmap


def upgrade() -> None:
    bind = op.get_bind()
    sessions = bind.execute(sa.text(
        "SELECT id, exam_set_id FROM exam_sessions "
        "WHERE status = 'submitted' AND result_snapshot IS NULL")).fetchall()

    set_cache: dict = {}
    for sid, exam_set_id in sessions:
        qmap = _set_questions(bind, exam_set_id, set_cache)
        answers = bind.execute(sa.text(
            "SELECT question_id, selected_letter, selected_letters, is_correct "
            "FROM exam_attempt_answers WHERE exam_session_id = :sid "
            "ORDER BY id"), {"sid": sid}).fetchall()

        snapshot = []
        for qid, sel_letter, sel_letters, ans_correct in answers:
            entry = qmap.get(qid)
            if entry is None:
                # Deleted / removed from the set — invisible in today's
                # review, so it stays out of the frozen one too.
                continue
            (q_id, stem, topic_id, domain, task, enablers, remarks,
             difficulty, question_type, explanation), opts = entry
            qtype = (question_type or "single_choice").lower()
            if qtype == "multi_choice":
                selected = set(_as_list(sel_letters))
            else:
                selected = {sel_letter} if sel_letter else set()
            snapshot.append({
                "id": q_id, "stem": stem, "topic_id": topic_id,
                "domain": domain, "task": task,
                "enablers": _as_list(enablers), "remarks": remarks,
                "difficulty": _DIFFICULTY_VALUES.get(
                    difficulty, (difficulty or "medium").lower()),
                "question_type": qtype,
                "explanation": explanation,
                "is_user_correct": bool(ans_correct),
                "options": [
                    {"option_letter": letter, "text": text,
                     "is_correct": bool(is_correct), "reasoning": reasoning,
                     "selected_by_user": letter in selected}
                    for letter, text, is_correct, reasoning in opts
                ],
            })

        bind.execute(_sessions_t.update()
                     .where(_sessions_t.c.id == sid)
                     .values(result_snapshot=snapshot))


def downgrade() -> None:
    # Forward-only (see module docstring): backfilled snapshots are
    # indistinguishable from submit-written ones and harmless to older
    # code, so there is nothing safe or useful to undo.
    pass
