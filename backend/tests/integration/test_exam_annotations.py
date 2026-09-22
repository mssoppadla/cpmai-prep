"""Highlight / strike marks made during an attempt survive submission
and come back on the result (incl. from the frozen snapshot path)."""
from tests.conftest import auth_header

ANN = {"stem": [{"start": 0, "end": 5, "kind": "highlight"}],
       "option-A": [{"start": 2, "end": 9, "kind": "strike"}]}


def _start(client, headers, sample_exam_set):
    r = client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start", headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_annotations_persist_and_return_on_result(client, user, sample_exam_set):
    headers = auth_header(client, user.email)
    attempt = _start(client, headers, sample_exam_set)
    qid = attempt["questions"][0]["id"]
    aid = attempt["id"]

    # save with marks
    r = client.patch(f"/api/v1/exams/attempts/{aid}/answer", headers=headers,
                     json={"question_id": qid, "selected_letter": "A",
                           "marked_for_review": True, "annotations": ANN})
    assert r.status_code == 204, r.text
    # reload the attempt: marks come from the server (new device / reload)
    r = client.get(f"/api/v1/exams/attempts/{aid}", headers=headers)
    assert r.json()["user_annotations"][str(qid)] == ANN

    # a plain answer save (no annotations key) must not wipe the marks
    r = client.patch(f"/api/v1/exams/attempts/{aid}/answer", headers=headers,
                     json={"question_id": qid, "selected_letter": "B",
                           "marked_for_review": True})
    assert r.status_code == 204
    r = client.get(f"/api/v1/exams/attempts/{aid}", headers=headers)
    assert r.json()["user_annotations"][str(qid)] == ANN

    # submit → result carries them, both live and from the snapshot path
    r = client.post(f"/api/v1/exams/attempts/{aid}/submit", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["questions"][0]["annotations"] == ANN
    r = client.get(f"/api/v1/exams/attempts/{aid}/result", headers=headers)
    assert r.status_code == 200
    assert r.json()["questions"][0]["annotations"] == ANN
    assert r.json()["questions"][0]["marked_for_review"] is True


def test_clearing_and_junk_ranges(client, user, sample_exam_set):
    headers = auth_header(client, user.email)
    attempt = _start(client, headers, sample_exam_set)
    qid = attempt["questions"][0]["id"]; aid = attempt["id"]
    base = {"question_id": qid, "selected_letter": "A", "marked_for_review": False}
    # junk: inverted / zero-length ranges dropped, empty targets dropped
    r = client.patch(f"/api/v1/exams/attempts/{aid}/answer", headers=headers,
                     json={**base, "annotations": {
                         "stem": [{"start": 9, "end": 3, "kind": "strike"},
                                  {"start": 1, "end": 4, "kind": "highlight"}],
                         "option-B": []}})
    assert r.status_code == 204, r.text
    r = client.get(f"/api/v1/exams/attempts/{aid}", headers=headers)
    assert r.json()["user_annotations"] == {str(qid): {"stem": [{"start": 1, "end": 4, "kind": "highlight"}]}}
    # bad kind → 422
    r = client.patch(f"/api/v1/exams/attempts/{aid}/answer", headers=headers,
                     json={**base, "annotations": {"stem": [{"start": 0, "end": 2, "kind": "bold"}]}})
    assert r.status_code == 422
    # {} clears
    r = client.patch(f"/api/v1/exams/attempts/{aid}/answer", headers=headers,
                     json={**base, "annotations": {}})
    assert r.status_code == 204
    r = client.get(f"/api/v1/exams/attempts/{aid}", headers=headers)
    assert r.json()["user_annotations"] == {}
    r = client.post(f"/api/v1/exams/attempts/{aid}/submit", headers=headers)
    assert r.json()["questions"][0]["annotations"] is None
