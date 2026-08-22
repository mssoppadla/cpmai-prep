"""Claim-on-login: a browser's anonymous history joins the account.

The browser's persistent id (localStorage ``cpmai.anon_token``) rides
every request as X-Anon-ID. At login/signup the backend links it to the
account (anon_identity_links) and backfills:

  * journey_events.user_id on that browser's anonymous rows
  * FINISHED anonymous exam attempts (submitted/abandoned) — results
    taken before login appear in the profile; in-progress drafts stay
    with the existing _adopt_orphan_draft path.

Plus: /track accepts the anon id in the batch BODY (sendBeacon can't
set headers), and anonymous exam submissions stamp their anon id onto
the journey event.
"""
from datetime import datetime, timedelta, timezone

from app.models.anon_identity_link import AnonIdentityLink
from app.models.exam_session import ExamSession
from app.models.journey_event import JourneyEvent
from tests.conftest import auth_header

AID = "11111111-2222-4333-8444-555555555555"


def _login(client, email, aid=AID):
    r = client.post("/api/v1/auth/login",
                    headers={"X-Anon-ID": aid},
                    json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return r


def _anon_exam(db, exam_set_id, *, status="submitted", aid=AID):
    now = datetime.now(timezone.utc)
    s = ExamSession(user_id=None, anon_token=aid, exam_set_id=exam_set_id,
                    status=status, score=70 if status == "submitted" else None,
                    passed=(status == "submitted") or None,
                    time_taken_seconds=600 if status == "submitted" else None,
                    started_at=now - timedelta(hours=1),
                    submitted_at=now if status == "submitted" else None,
                    expires_at=now + timedelta(hours=1))
    db.add(s); db.commit(); db.refresh(s)
    return s


def test_login_links_and_backfills_journey_history(client, db, user):
    db.add(JourneyEvent(event="page.view", anon_id=AID))
    db.add(JourneyEvent(event="page.view", anon_id="other-browser"))
    db.commit()

    _login(client, user.email)

    link = db.query(AnonIdentityLink).filter_by(anon_id=AID).one()
    assert link.user_id == user.id
    mine = db.query(JourneyEvent).filter_by(anon_id=AID).all()
    assert all(e.user_id == user.id for e in mine)
    other = db.query(JourneyEvent).filter_by(anon_id="other-browser").one()
    assert other.user_id is None                 # only THIS browser claimed


def test_login_claims_submitted_anon_exam_into_profile(
        client, db, user, sample_exam_set):
    s = _anon_exam(db, sample_exam_set.id, status="submitted")

    _login(client, user.email)

    db.refresh(s)
    assert s.user_id == user.id
    assert s.anon_token is None      # unclaimable by a later account
    # …and it now shows in the signed-in attempt history.
    h = auth_header(client, user.email)
    r = client.get("/api/v1/exams/attempts", headers=h)
    assert r.status_code == 200
    assert any(a["id"] == s.id for a in r.json())


def test_login_leaves_in_progress_draft_to_adoption_path(
        client, db, user, sample_exam_set):
    """Live drafts are NOT claimed at login — the start-attempt
    adoption path owns that (claiming here could collide with the
    one-live-draft-per-user-set unique index)."""
    s = _anon_exam(db, sample_exam_set.id, status="in_progress")
    _login(client, user.email)
    db.refresh(s)
    assert s.user_id is None
    assert s.anon_token == AID


def test_signup_links_too(client, db):
    db.add(JourneyEvent(event="page.view", anon_id=AID))
    db.commit()
    r = client.post("/api/v1/auth/signup",
                    headers={"X-Anon-ID": AID},
                    json={"email": "fresh@example.com",
                          "password": "password123", "name": "Fresh"})
    assert r.status_code == 201, r.text
    uid = r.json()["user"]["id"]
    assert db.query(AnonIdentityLink).filter_by(
        anon_id=AID).one().user_id == uid
    # page.view (seeded) backfilled; the signup's own auth.signup event
    # also carries the anon_id — both rows belong to the new account.
    rows = db.query(JourneyEvent).filter_by(anon_id=AID).all()
    assert rows and all(e.user_id == uid for e in rows)


def test_shared_browser_relinks_to_most_recent_login(client, db, user,
                                                     admin):
    _login(client, user.email)
    assert db.query(AnonIdentityLink).filter_by(
        anon_id=AID).one().user_id == user.id
    _login(client, admin.email)
    link = db.query(AnonIdentityLink).filter_by(anon_id=AID).one()
    db.refresh(link)
    assert link.user_id == admin.id              # latest login wins


def test_login_without_anon_id_is_a_noop(client, db, user):
    r = client.post("/api/v1/auth/login",
                    json={"email": user.email, "password": "password123"})
    assert r.status_code == 200
    assert db.query(AnonIdentityLink).count() == 0


def test_track_accepts_anon_id_in_body(client, db):
    """sendBeacon flushes can't set headers — the batch body carries
    the id and the endpoint stamps it onto every event."""
    r = client.post("/api/v1/track", json={
        "anon_id": AID,
        "events": [{"event": "page.view", "path": "/pricing"}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 1
    row = db.query(JourneyEvent).filter_by(event="page.view").one()
    assert row.anon_id == AID


def test_track_header_wins_over_body(client, db):
    r = client.post("/api/v1/track",
                    headers={"X-Anon-ID": "header-id"},
                    json={"anon_id": "body-id",
                          "events": [{"event": "page.view", "path": "/"}]})
    assert r.status_code == 200
    row = db.query(JourneyEvent).filter_by(event="page.view").one()
    assert row.anon_id == "header-id"


def test_gdpr_delete_drops_identity_links(client, db, user):
    _login(client, user.email)
    assert db.query(AnonIdentityLink).filter_by(user_id=user.id).count() == 1
    from app.services.user_deletion import soft_delete_user
    assert soft_delete_user(db, user) is True
    assert db.query(AnonIdentityLink).filter_by(user_id=user.id).count() == 0


# ============================================== /shared-access detection

def test_shared_access_requires_admin(client, user):
    h = auth_header(client, user.email)
    r = client.get("/api/v1/admin/anonymous-traffic/shared-access",
                   headers=h)
    assert r.status_code in (401, 403)


def test_shared_access_flags_ip_and_browser_reuse(client, db, user, admin):
    """Two accounts from the same browser (X-Anon-ID) and, via the
    test client, the same IP: both signals must surface with both
    accounts listed. A browser/IP used by only ONE account must not."""
    _login(client, user.email, aid=AID)              # account 1, browser AID
    _login(client, admin.email, aid=AID)             # account 2, same browser
    _login(client, admin.email, aid="admin-only-browser")   # solo browser

    h = auth_header(client, admin.email)
    body = client.get(
        "/api/v1/admin/anonymous-traffic/shared-access?window=30d",
        headers=h).json()

    # Same browser, two accounts → flagged with both emails.
    shared = {b["anon_id"]: b for b in body["shared_browsers"]}
    assert AID in shared
    emails = {u["email"] for u in shared[AID]["users"]}
    assert emails == {user.email, admin.email}
    # Solo browser never flagged.
    assert "admin-only-browser" not in shared

    # Test client logins all come from one IP → the two accounts show
    # as sharing it, with per-account login counts.
    assert len(body["shared_ips"]) == 1
    ip_users = {u["email"]: u for u in body["shared_ips"][0]["users"]}
    assert set(ip_users) == {user.email, admin.email}
    assert ip_users[admin.email]["logins"] >= 2   # logged in twice+

def test_shared_access_empty_when_no_reuse(client, db, user, admin):
    _login(client, user.email, aid="browser-a")
    h = auth_header(client, admin.email)   # admin logs in (same test IP)
    body = client.get(
        "/api/v1/admin/anonymous-traffic/shared-access?window=7d",
        headers=h).json()
    assert body["shared_browsers"] == []
    # Both accounts DID authenticate from the client IP — that's real
    # sharing per the signal's definition, so it may legitimately list
    # the IP. Pin only that solo browsers stay unflagged here.


def test_login_audit_records_forwarded_client_ip(client, db, user):
    """Behind Caddy, request.client.host is the proxy's PRIVATE address
    — every historical login audit stamped 172.16.x, which blinded
    shared-IP detection. The audit ctx must honor X-Forwarded-For
    (trusted-proxy depth 1): rightmost untrusted hop wins."""
    r = client.post("/api/v1/auth/login",
                    headers={"X-Forwarded-For": "203.0.113.77, 172.16.2.1"},
                    json={"email": user.email, "password": "password123"})
    assert r.status_code == 200
    from app.models.audit_log import AuditLog
    row = (db.query(AuditLog)
           .filter_by(action="auth.login.success", user_id=user.id)
           .order_by(AuditLog.id.desc()).first())
    assert row is not None
    assert row.ip == "203.0.113.77"


def test_shared_access_ignores_private_proxy_ips(client, db, user, admin):
    """Legacy audits all carry the proxy's private IP — grouping them
    renders the whole user base as one fake shared IP. Private and
    loopback addresses never surface; real public IPs still do."""
    from app.models.audit_log import AuditLog
    for uid in (user.id, admin.id):
        db.add(AuditLog(user_id=uid, action="auth.login.success",
                        ip="172.16.2.1", metadata_json={}))
        db.add(AuditLog(user_id=uid, action="auth.login.success",
                        ip="8.8.8.8", metadata_json={}))
    db.commit()
    h = auth_header(client, admin.email)
    body = client.get(
        "/api/v1/admin/anonymous-traffic/shared-access?window=7d",
        headers=h).json()
    ips = {r["ip"] for r in body["shared_ips"]}
    assert "8.8.8.8" in ips
    assert "172.16.2.1" not in ips
