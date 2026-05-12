"""Human-in-the-loop: flag turn → admin queue → admin reply → user sees it.

Covers the four state transitions on assistant_flagged_turns:
  • create (POST /assistant/turns/{id}/flag)
  • idempotency (re-flag is a no-op, not an error)
  • admin replies (POST /admin/chat-history/turns/{flag_id}/reply)
  • user picks up the reply (GET /assistant/notifications + mark seen)
"""
import pytest
from app.models.assistant_log import AssistantLog
from app.models.assistant_flagged_turn import AssistantFlaggedTurn
from tests.conftest import auth_header


@pytest.fixture
def log_row(db, user):
    """A captured chat turn for `user`, ready to be flagged."""
    row = AssistantLog(
        user_id=user.id, anon_id=None,
        intent="faq", intent_confidence=0.9,
        provider="stub", model="stub-v1",
        redacted_input="When is the next exam?",
        response_preview="The exam is quarterly...",
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def test_user_flags_turn_creates_pending_row(client, user, log_row, db):
    h = auth_header(client, user.email)
    r = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                    json={"note": "Actually it's monthly."}, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["assistant_log_id"] == log_row.id
    assert body["status"] == "pending"

    db.expire_all()
    row = db.query(AssistantFlaggedTurn).filter_by(
        assistant_log_id=log_row.id).first()
    assert row is not None
    assert row.user_id == user.id
    assert row.flag_note == "Actually it's monthly."
    assert row.replied_at is None


def test_flag_is_idempotent(client, user, log_row):
    h = auth_header(client, user.email)
    r1 = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                     json={}, headers=h)
    r2 = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                     json={"note": "different note now"}, headers=h)
    assert r1.status_code == 201
    assert r2.status_code == 201   # not 409 — second flag returns existing
    assert r1.json()["id"] == r2.json()["id"]


def test_other_users_cannot_flag_my_turn(client, user, admin, log_row):
    h = auth_header(client, admin.email)
    r = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                    json={}, headers=h)
    assert r.status_code == 404  # not 403 — no enumeration


def test_admin_sees_pending_queue_and_replies(client, user, admin,
                                              log_row, db):
    # User flags
    uh = auth_header(client, user.email)
    fr = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                     json={"note": "wrong"}, headers=uh)
    assert fr.status_code == 201
    flag_id = fr.json()["id"]

    # Admin sees it in queue
    ah = auth_header(client, admin.email)
    qr = client.get("/api/v1/admin/chat-history/flagged", headers=ah)
    assert qr.status_code == 200
    items = qr.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == flag_id
    assert items[0]["original_message"] == log_row.redacted_input

    # Admin replies
    rr = client.post(f"/api/v1/admin/chat-history/turns/{flag_id}/reply",
                     json={"reply": "Actually it's monthly. Sorry!"},
                     headers=ah)
    assert rr.status_code == 200, rr.text

    # No longer in pending queue
    qr2 = client.get("/api/v1/admin/chat-history/flagged", headers=ah)
    assert qr2.json()["items"] == []

    # But appears with include_replied=true
    qr3 = client.get("/api/v1/admin/chat-history/flagged"
                     "?include_replied=true", headers=ah)
    assert len(qr3.json()["items"]) == 1


def test_admin_cannot_double_reply(client, user, admin, log_row):
    uh = auth_header(client, user.email)
    flag_id = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                          json={}, headers=uh).json()["id"]
    ah = auth_header(client, admin.email)
    r1 = client.post(f"/api/v1/admin/chat-history/turns/{flag_id}/reply",
                     json={"reply": "First reply."}, headers=ah)
    assert r1.status_code == 200
    r2 = client.post(f"/api/v1/admin/chat-history/turns/{flag_id}/reply",
                     json={"reply": "Second reply."}, headers=ah)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "already_replied"


def test_user_sees_notification_then_marks_seen(client, user, admin,
                                                 log_row):
    uh = auth_header(client, user.email)
    flag_id = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                          json={}, headers=uh).json()["id"]
    ah = auth_header(client, admin.email)
    client.post(f"/api/v1/admin/chat-history/turns/{flag_id}/reply",
                json={"reply": "Here is the correct answer."}, headers=ah)

    # User's notifications now contains the reply
    nr = client.get("/api/v1/assistant/notifications", headers=uh)
    assert nr.status_code == 200
    notes = nr.json()
    assert len(notes) == 1
    assert notes[0]["admin_reply"] == "Here is the correct answer."

    # Mark seen — clears it from notifications
    sr = client.post(f"/api/v1/assistant/notifications/{notes[0]['id']}/seen",
                     headers=uh)
    assert sr.status_code == 204

    nr2 = client.get("/api/v1/assistant/notifications", headers=uh)
    assert nr2.json() == []


def test_admin_chat_history_users_includes_flag_count(client, user, admin,
                                                       log_row):
    uh = auth_header(client, user.email)
    client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                json={}, headers=uh)

    ah = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/chat-history/users", headers=ah)
    assert r.status_code == 200
    users = r.json()["users"]
    me = next(u for u in users if u["user_id"] == user.id)
    assert me["flagged"] == 1
