"""Expired-token draft handling — regression pins for the 2026-08-07
prod incident where a silently-expired access token created anon-owned
drafts for signed-in users, stranding their answers.

Contract:
  1. A PRESENT-but-invalid Bearer must 401 (never silently fall back to
     the anon identity) so the frontend's silent-refresh interceptor can
     recover the session and the draft is owned by the right account.
  2. An anon-owned draft is ADOPTED when the same browser (same
     X-Anon-Token) starts the set signed-in — answers carried over,
     saves working, no duplicate empty draft.
"""
from tests.conftest import auth_header

ANON = {"X-Anon-Token": "anon-regression-0123456789"}
BAD_BEARER = {"Authorization": "Bearer not.a.valid.token", **ANON}


def test_present_but_invalid_bearer_is_401_not_anon(client, sample_exam_set):
    """Expired/garbage token + anon header → 401, and no session row is
    created under the anon identity."""
    r = client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start",
                    headers=BAD_BEARER)
    assert r.status_code == 401, r.text
    # The same anon identity WITHOUT the bad bearer starts cleanly with a
    # brand-new (empty) attempt — nothing was created by the 401 call.
    r2 = client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start",
                     headers=ANON)
    assert r2.status_code == 201, r2.text
    assert all(v is None for v in r2.json()["user_answers"].values())


def test_missing_bearer_still_allows_anon(client, sample_exam_set):
    """Anon fallback is only narrowed, not removed: no Authorization
    header at all + anon token still starts a free-set attempt."""
    r = client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start",
                    headers=ANON)
    assert r.status_code == 201, r.text


def test_signed_in_start_adopts_orphan_anon_draft(client, user, sample_exam_set):
    """An anon draft with saved answers is transferred to the account on
    the first signed-in start from the same browser: same attempt id,
    answers intact, signed-in saves accepted."""
    # 1. Anon browser creates a draft and answers a question.
    a = client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start",
                    headers=ANON).json()
    qid = a["questions"][0]["id"]
    r = client.patch(f"/api/v1/exams/attempts/{a['id']}/answer", headers=ANON,
                     json={"question_id": qid, "selected_letter": "C"})
    assert r.status_code == 204, r.text

    # 2. Same browser signs in and starts the set → adopts, not duplicates.
    headers = {**auth_header(client, user.email), **ANON}
    adopted = client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start",
                          headers=headers).json()
    assert adopted["id"] == a["id"]
    assert adopted["user_answers"][str(qid)] == "C"

    # 3. Signed-in saves to the adopted draft now succeed (was 403).
    r = client.patch(f"/api/v1/exams/attempts/{a['id']}/answer",
                     headers=auth_header(client, user.email),
                     json={"question_id": qid, "selected_letter": "D"})
    assert r.status_code == 204, r.text

    # 4. The draft shows up in the account's history as in_progress.
    rows = client.get("/api/v1/exams/attempts",
                      headers=auth_header(client, user.email)).json()
    assert [x["id"] for x in rows if x["status"] == "in_progress"] == [a["id"]]
