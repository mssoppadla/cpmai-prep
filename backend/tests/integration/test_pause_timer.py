"""Pause-on-leave exam timer — the clock measures time on screen.

Contract (2026-08-07 redesign, superseding the fixed wall-clock deadline):
- remaining_seconds is the active-time budget, charged on activity
  events (heartbeat / answer save / resume), each gap capped at
  ACTIVITY_CHARGE_CAP_SECONDS so time away is never billed;
- a paused draft (stale expires_at, budget left) stays resumable;
- a drained draft with NOTHING answered is discarded, not minted into
  a 0% history row; with answers it auto-submits with an honest stamp;
- auto_submitted is an explicit column, set by clock-driven paths only.
"""
from datetime import datetime, timedelta, timezone

from app.models.exam_session import ExamSession
from app.services.exam_service import ExamService
from tests.conftest import auth_header

ANON = {"X-Anon-Token": "anon-pause-timer-0123456789"}


def _start(client, headers, slug):
    return client.post(f"/api/v1/exam-sets/{slug}/start", headers=headers).json()


def test_start_seeds_budget_and_heartbeat_charges_capped(client, user, db,
                                                         sample_exam_set):
    headers = auth_header(client, user.email)
    a = _start(client, headers, sample_exam_set.slug)
    s = db.get(ExamSession, a["id"])
    assert s.remaining_seconds == sample_exam_set.time_limit_minutes * 60
    assert s.last_activity_at is not None

    # Simulate a long-gone candidate: last activity 2 hours ago. The next
    # heartbeat must charge AT MOST the cap — never the 2 hours.
    s.last_activity_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()
    r = client.post(f"/api/v1/exams/attempts/{a['id']}/heartbeat",
                    headers=headers)
    assert r.status_code == 200
    remaining = r.json()["remaining_seconds"]
    budget = sample_exam_set.time_limit_minutes * 60
    assert budget - ExamService.ACTIVITY_CHARGE_CAP_SECONDS <= remaining < budget


def test_paused_draft_with_stale_deadline_is_still_resumable(client, user, db,
                                                             sample_exam_set):
    headers = auth_header(client, user.email)
    a = _start(client, headers, sample_exam_set.slug)
    # Paused for a week: wall-clock deadline long past, budget intact.
    s = db.get(ExamSession, a["id"])
    s.expires_at = datetime.now(timezone.utc) - timedelta(days=7)
    s.last_activity_at = datetime.now(timezone.utc) - timedelta(days=7)
    db.commit()

    # The set still reports a live draft (budget-based liveness) …
    summary = client.get(f"/api/v1/exam-sets/{sample_exam_set.slug}",
                         headers=headers).json()
    assert summary["in_progress"] is True

    # … and start RESUMES it with a re-anchored (future) deadline.
    resumed = _start(client, headers, sample_exam_set.slug)
    assert resumed["id"] == a["id"]
    assert datetime.fromisoformat(resumed["expires_at"]) \
        > datetime.now(timezone.utc)


def test_drained_zero_answer_draft_is_abandoned_not_scored(client, user, db,
                                                           sample_exam_set):
    """Empty drained draft disappears from every view — but the ROW
    survives: exam_sessions is a GUARDED_TABLE and deploy.sh aborts when
    guarded rows vanish (incident 2026-08-07)."""
    headers = auth_header(client, user.email)
    a = _start(client, headers, sample_exam_set.slug)
    s = db.get(ExamSession, a["id"])
    s.remaining_seconds = 0
    db.commit()

    # History sweep: no 0% junk row, and no resumable draft either.
    rows = client.get("/api/v1/exams/attempts", headers=headers).json()
    assert all(x["id"] != a["id"] for x in rows)
    # Row preserved, marked — and unreachable through the API.
    db.expire_all()
    assert db.get(ExamSession, a["id"]).status == "abandoned"
    assert client.get(f"/api/v1/exams/attempts/{a['id']}",
                      headers=headers).status_code == 404


def test_removed_attempt_is_soft_and_row_survives(client, user, db,
                                                  sample_exam_set):
    """Deleting from history is a SOFT removal for the same guard
    reason: a user tidying their history mid-deploy must not abort a
    production deploy."""
    headers = auth_header(client, user.email)
    a = _start(client, headers, sample_exam_set.slug)
    client.post(f"/api/v1/exams/attempts/{a['id']}/submit", headers=headers)

    r = client.delete(f"/api/v1/exams/attempts/{a['id']}", headers=headers)
    assert r.status_code == 204
    # Gone from history and unreachable …
    rows = client.get("/api/v1/exams/attempts", headers=headers).json()
    assert all(x["id"] != a["id"] for x in rows)
    assert client.get(f"/api/v1/exams/attempts/{a['id']}/result",
                      headers=headers).status_code == 404
    # … but the row (and its answers) are still there.
    db.expire_all()
    assert db.get(ExamSession, a["id"]).status == "deleted"


def test_drained_draft_with_answers_auto_submits_honestly(client, user, db,
                                                          sample_exam_set):
    headers = auth_header(client, user.email)
    a = _start(client, headers, sample_exam_set.slug)
    qid = a["questions"][0]["id"]
    r = client.patch(f"/api/v1/exams/attempts/{a['id']}/answer",
                     headers=headers,
                     json={"question_id": qid, "selected_letter": "B"})
    assert r.status_code == 204
    last_touch = datetime.now(timezone.utc) - timedelta(days=3)
    s = db.get(ExamSession, a["id"])
    s.remaining_seconds = 0
    s.last_activity_at = last_touch
    db.commit()

    rows = client.get("/api/v1/exams/attempts", headers=headers).json()
    row = next(x for x in rows if x["id"] == a["id"])
    assert row["status"] == "submitted"
    assert row["auto_submitted"] is True
    # Honest stamp: the candidate's last activity, not the sweep moment.
    stamped = datetime.fromisoformat(row["submitted_at"])
    assert abs((stamped - last_touch).total_seconds()) < 5


def test_deliberate_submit_is_not_labeled_auto(client, user, sample_exam_set):
    headers = auth_header(client, user.email)
    a = _start(client, headers, sample_exam_set.slug)
    client.post(f"/api/v1/exams/attempts/{a['id']}/submit", headers=headers)
    rows = client.get("/api/v1/exams/attempts", headers=headers).json()
    row = next(x for x in rows if x["id"] == a["id"])
    assert row["auto_submitted"] is False


def test_time_up_submit_with_auto_flag_is_labeled(client, user, sample_exam_set):
    headers = auth_header(client, user.email)
    a = _start(client, headers, sample_exam_set.slug)
    client.post(f"/api/v1/exams/attempts/{a['id']}/submit?auto=true",
                headers=headers)
    rows = client.get("/api/v1/exams/attempts", headers=headers).json()
    row = next(x for x in rows if x["id"] == a["id"])
    assert row["auto_submitted"] is True


def test_heartbeat_works_for_anon_sittings(client, sample_exam_set):
    a = _start(client, ANON, sample_exam_set.slug)
    r = client.post(f"/api/v1/exams/attempts/{a['id']}/heartbeat",
                    headers=ANON)
    assert r.status_code == 200
    assert r.json()["remaining_seconds"] > 0
