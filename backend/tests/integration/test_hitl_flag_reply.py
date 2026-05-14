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


def test_flag_resubmit_merges_in_a_real_note_after_empty_first_submit(
        client, user, log_row, db,
):
    """REGRESSION GUARD for the bug an operator reported on
    /admin/chat-history/flagged where 'something' (or any first-typed
    string) was stuck on the row even after the user re-typed a real
    note.

    Pre-fix behaviour: the flag endpoint silently returned the existing
    row on re-submit without updating flag_note. So a user who hit
    Send empty first, then typed a real note and hit Send again, never
    got their note to the admin queue.

    Post-fix behaviour: an empty first submit + non-empty second submit
    merges the new note onto the existing row."""
    h = auth_header(client, user.email)
    # First submit — no note (user clicked "Wasn't helpful?" too fast).
    r1 = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                      json={}, headers=h)
    assert r1.status_code == 201

    # Second submit — user types a real note this time.
    r2 = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                      json={"note": "the answer doesn't have the cost details"},
                      headers=h)
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]   # same row

    # The DB row has the SECOND note — not the first (empty) one.
    db.expire_all()
    row = db.query(AssistantFlaggedTurn).filter_by(
        assistant_log_id=log_row.id).first()
    assert row.flag_note == "the answer doesn't have the cost details"


def test_flag_resubmit_with_empty_note_keeps_existing_real_note(
        client, user, log_row, db,
):
    """Inverse case: the user typed a real note first, then re-clicks
    with no note (e.g., accidental re-flag). Don't blow away their
    note. Note-merge is one-way: newer non-empty wins, but a newer
    empty doesn't clear an existing real note."""
    h = auth_header(client, user.email)
    client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                 json={"note": "the real note"}, headers=h)
    client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                 json={}, headers=h)

    db.expire_all()
    row = db.query(AssistantFlaggedTurn).filter_by(
        assistant_log_id=log_row.id).first()
    assert row.flag_note == "the real note"


def test_flag_notes_isolated_across_users(client, user, admin, db):
    """Each user's flag stays on its own row with its own flag_note.
    Confirms there's no cross-row contamination in the admin queue —
    A's note never leaks onto B's row or vice versa."""
    from tests.conftest import auth_header as ah_

    # Two separate AssistantLog rows, one per user.
    log_a = AssistantLog(
        user_id=user.id, intent="faq", intent_confidence=0.9,
        provider="stub", model="stub-v1",
        redacted_input="A's question", response_preview="A's reply")
    log_b = AssistantLog(
        user_id=admin.id, intent="faq", intent_confidence=0.9,
        provider="stub", model="stub-v1",
        redacted_input="B's question", response_preview="B's reply")
    db.add(log_a); db.add(log_b); db.commit()
    db.refresh(log_a); db.refresh(log_b)

    # Each user flags their own turn with a distinct note.
    h_a = ah_(client, user.email)
    h_b = ah_(client, admin.email)
    r_a = client.post(f"/api/v1/assistant/turns/{log_a.id}/flag",
                       json={"note": "note from user A"}, headers=h_a)
    r_b = client.post(f"/api/v1/assistant/turns/{log_b.id}/flag",
                       json={"note": "note from user B"}, headers=h_b)
    assert r_a.status_code == 201
    assert r_b.status_code == 201
    assert r_a.json()["id"] != r_b.json()["id"]

    # Admin queue returns both rows, each with its OWN note.
    h_admin = ah_(client, admin.email)
    body = client.get("/api/v1/admin/chat-history/flagged",
                       headers=h_admin).json()
    by_id = {it["id"]: it for it in body["items"]}
    assert by_id[r_a.json()["id"]]["flag_note"] == "note from user A"
    assert by_id[r_b.json()["id"]]["flag_note"] == "note from user B"


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


# ===================================================== resolve / withdraw

class TestUserResolve:
    """User can mark their own flag as resolved — either to withdraw a
    pending flag they raised in error, or to acknowledge a satisfying
    admin reply."""

    def test_user_resolves_their_own_pending_flag(
            self, client, user, log_row, db,
    ):
        uh = auth_header(client, user.email)
        client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                     json={"note": "I'll work it out"}, headers=uh)

        rr = client.post(
            f"/api/v1/assistant/turns/{log_row.id}/flag/resolve",
            headers=uh)
        assert rr.status_code == 200
        body = rr.json()
        assert body["status"] == "resolved"
        assert body["resolved_by_self"] is True

        db.expire_all()
        row = db.query(AssistantFlaggedTurn).filter_by(
            assistant_log_id=log_row.id).first()
        assert row.resolved_at is not None
        assert row.resolved_by == user.id

    def test_user_resolve_is_idempotent(self, client, user, log_row, db):
        uh = auth_header(client, user.email)
        client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                     json={}, headers=uh)
        r1 = client.post(
            f"/api/v1/assistant/turns/{log_row.id}/flag/resolve",
            headers=uh)
        r2 = client.post(
            f"/api/v1/assistant/turns/{log_row.id}/flag/resolve",
            headers=uh)
        assert r1.json()["resolved_at"] == r2.json()["resolved_at"]

    def test_user_cannot_resolve_someone_elses_flag(
            self, client, user, admin, log_row,
    ):
        uh = auth_header(client, user.email)
        client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                     json={}, headers=uh)
        # Admin trying via the USER endpoint — log isn't theirs → 404.
        ah = auth_header(client, admin.email)
        rr = client.post(
            f"/api/v1/assistant/turns/{log_row.id}/flag/resolve",
            headers=ah)
        assert rr.status_code == 404

    def test_user_resolve_with_no_flag_is_a_noop_not_an_error(
            self, client, user, log_row,
    ):
        """Edge case: user calls resolve before flagging. Not an error
        (avoids surprising the client) — returns not_flagged status."""
        uh = auth_header(client, user.email)
        rr = client.post(
            f"/api/v1/assistant/turns/{log_row.id}/flag/resolve",
            headers=uh)
        assert rr.status_code == 200
        assert rr.json()["status"] == "not_flagged"


class TestAdminResolve:
    """Admin can close any flagged turn from the admin queue. Useful
    when the user never opens chat again after flagging, or when the
    admin decides the flag is non-actionable."""

    def test_admin_resolves_a_pending_flag(self, client, user, admin,
                                            log_row, db):
        uh = auth_header(client, user.email)
        fr = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                          json={"note": "stuck on phase 3"}, headers=uh)
        flag_id = fr.json()["id"]

        ah = auth_header(client, admin.email)
        rr = client.post(
            f"/api/v1/admin/chat-history/turns/{flag_id}/resolve",
            headers=ah)
        assert rr.status_code == 200
        body = rr.json()
        assert body["resolved_by_admin"] is True

        db.expire_all()
        row = db.get(AssistantFlaggedTurn, flag_id)
        assert row.resolved_at is not None
        assert row.resolved_by == admin.id

    def test_admin_resolve_can_close_a_replied_flag(
            self, client, user, admin, log_row, db,
    ):
        """Common end-of-day scenario: admin replied earlier, the user
        never opened the widget to acknowledge. Admin clears the row
        from the queue with the resolve button."""
        uh = auth_header(client, user.email)
        fr = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                          json={"note": "x"}, headers=uh)
        flag_id = fr.json()["id"]

        ah = auth_header(client, admin.email)
        client.post(f"/api/v1/admin/chat-history/turns/{flag_id}/reply",
                     headers=ah, json={"reply": "Here's the answer."})
        rr = client.post(
            f"/api/v1/admin/chat-history/turns/{flag_id}/resolve",
            headers=ah)
        assert rr.status_code == 200

        db.expire_all()
        row = db.get(AssistantFlaggedTurn, flag_id)
        assert row.replied_at is not None
        assert row.resolved_at is not None

    def test_admin_resolve_requires_admin_auth(self, client, user, log_row):
        uh = auth_header(client, user.email)
        fr = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                          json={}, headers=uh)
        flag_id = fr.json()["id"]

        # Regular user hitting the admin endpoint → 401 or 403.
        rr = client.post(
            f"/api/v1/admin/chat-history/turns/{flag_id}/resolve",
            headers=uh)
        assert rr.status_code in (401, 403)


class TestAdminQueueFilters:
    """Default admin GET hides resolved rows; include_resolved=true
    surfaces them for audit."""

    def test_default_queue_excludes_resolved(
            self, client, user, admin, log_row,
    ):
        uh = auth_header(client, user.email)
        ah = auth_header(client, admin.email)
        fr = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                          json={"note": "withdrawing this"}, headers=uh)
        client.post(
            f"/api/v1/assistant/turns/{log_row.id}/flag/resolve",
            headers=uh)

        body = client.get("/api/v1/admin/chat-history/flagged",
                           headers=ah).json()
        assert body["items"] == []

    def test_include_resolved_surfaces_them(
            self, client, user, admin, log_row,
    ):
        uh = auth_header(client, user.email)
        ah = auth_header(client, admin.email)
        client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                     json={}, headers=uh)
        client.post(
            f"/api/v1/assistant/turns/{log_row.id}/flag/resolve",
            headers=uh)

        body = client.get(
            "/api/v1/admin/chat-history/flagged?include_resolved=true",
            headers=ah).json()
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["status"] == "resolved"
        assert item["resolved_by"]["is_self"] is True   # user resolved their own

    def test_admin_resolve_shows_is_self_false(
            self, client, user, admin, log_row,
    ):
        """When the admin resolves, resolved_by.is_self should be false
        on the user's perspective (the admin is not the same user_id
        as the flagger). Used by the dashboard to show 'closed by
        admin' vs 'withdrawn by user' labels."""
        uh = auth_header(client, user.email)
        ah = auth_header(client, admin.email)
        fr = client.post(f"/api/v1/assistant/turns/{log_row.id}/flag",
                          json={}, headers=uh)
        flag_id = fr.json()["id"]
        client.post(f"/api/v1/admin/chat-history/turns/{flag_id}/resolve",
                     headers=ah)

        body = client.get(
            "/api/v1/admin/chat-history/flagged?include_resolved=true",
            headers=ah).json()
        item = body["items"][0]
        assert item["resolved_by"]["is_self"] is False
