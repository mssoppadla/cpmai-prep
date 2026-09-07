"""Access-lifecycle pins (prod incident 2026-09-06).

The incident, in two sentences: subscription-derived enrollments were a
one-way copy of the entitlement — revoking the subscription, unticking
the course from the plan, or the sub simply expiring never removed
course access; and granting a plan only took effect when each student
happened to log in. These tests pin the corrected behaviour:

  * revoke subscription  → its enrollments revoked, access gone
  * untick course from plan → subscription-derived access gone on next read
  * subscription expiry  → access gone (no cron; read-time gate)
  * enrollment expires_at → enforced (admin grants included)
  * plan-link save       → enrollments backfilled for active subscribers
  * grant                → enrollments materialized immediately + unlock
                           summary in the response
  * extend subscription  → derived enrollment expiry follows
  * contacts widget      → one human = one known visitor across sign-in
                           states and devices
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.anon_identity_link import AnonIdentityLink
from app.models.journey_event import JourneyEvent
from app.models.lms import Course, Enrollment
from app.models.subscription import Subscription
from tests.conftest import auth_header

PLANS = "/api/v1/admin/plans"
MY_ENROLLMENTS = "/api/v1/lms/me/enrollments"
GRANT = "/api/v1/admin/users/{uid}/subscriptions"
REVOKE = "/api/v1/admin/subscriptions/{sid}/revoke"
EXTEND = "/api/v1/admin/subscriptions/{sid}/extend"


@pytest.fixture
def course(db, admin):
    c = Course(tenant_id=1, slug="lifecycle-course", title="Lifecycle Course",
               base_price_paise=0, currency="INR",
               enrollment_type="subscription_bundle",
               is_published=False, created_by=admin.id)
    db.add(c); db.commit(); db.refresh(c)
    return c


def _mk_plan(client, admin, course_ids, slug):
    r = client.post(
        PLANS, headers=auth_header(client, admin.email),
        json={"name": f"Plan {slug}", "slug": slug, "bundle_type": "custom",
              "base_price_paise": 100000, "duration_days": 365,
              "is_active": True, "course_ids": course_ids},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _grant(client, admin, uid, plan_id, days=30):
    r = client.post(
        GRANT.format(uid=uid), headers=auth_header(client, admin.email),
        json={"plan_id": plan_id, "period_days": days, "reason": "lifecycle test"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _my_course_ids(client, user):
    r = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    assert r.status_code == 200, r.text
    return [e["course_id"] for e in r.json()]


# ------------------------------------------------------------- grant side

def test_grant_materializes_enrollment_immediately(client, db, admin, user, course):
    """No login needed: the enrollment row exists as soon as the admin
    grants, and the response says what unlocked."""
    plan_id = _mk_plan(client, admin, [course.id], "lc-grant")
    body = _grant(client, admin, user.id, plan_id)
    assert body["unlocks"]["courses"], body
    assert body["unlocks"]["courses"][0]["course_id"] == course.id
    assert body["unlocks"]["courses"][0]["action"] == "created"
    e = db.query(Enrollment).filter_by(user_id=user.id,
                                       course_id=course.id).first()
    assert e is not None and e.revoked_at is None
    assert e.subscription_id == body["id"]
    assert course.id in _my_course_ids(client, user)


def test_plan_link_save_backfills_active_subscribers(client, db, admin, user, course):
    """Adding a course to a plan enrolls existing active subscribers at
    save time — the prod gap where access silently depended on each
    student's next login."""
    plan_id = _mk_plan(client, admin, [], "lc-backfill")
    _grant(client, admin, user.id, plan_id)
    assert course.id not in _my_course_ids(client, user)

    r = client.patch(
        f"{PLANS}/{plan_id}", headers=auth_header(client, admin.email),
        json={"course_ids": [course.id]},
    )
    assert r.status_code == 200, r.text
    e = db.query(Enrollment).filter_by(user_id=user.id,
                                       course_id=course.id).first()
    assert e is not None, "backfill did not create the enrollment"
    assert course.id in _my_course_ids(client, user)


# ------------------------------------------------------------- revoke side

def test_revoke_subscription_cascades_and_removes_access(client, db, admin, user, course):
    plan_id = _mk_plan(client, admin, [course.id], "lc-revoke")
    body = _grant(client, admin, user.id, plan_id)
    assert course.id in _my_course_ids(client, user)

    r = client.post(REVOKE.format(sid=body["id"]),
                    headers=auth_header(client, admin.email),
                    json={"reason": "refund issued"})
    assert r.status_code == 200, r.text
    assert course.id not in _my_course_ids(client, user)
    e = db.query(Enrollment).filter_by(user_id=user.id,
                                       course_id=course.id).first()
    db.refresh(e)
    assert e.revoked_at is not None, "cascade did not revoke the enrollment"


def test_legacy_enrollment_without_fk_dies_on_read(client, db, admin, user, course):
    """Pre-migration rows (no subscription_id) whose backing sub is
    revoked lose access via read-time revalidation — the cpmaiexamprep
    'immortal access' case."""
    plan_id = _mk_plan(client, admin, [course.id], "lc-legacy")
    now = datetime.now(timezone.utc)
    sub = Subscription(user_id=user.id, plan="lc-legacy", plan_id=plan_id,
                       status="active", expires_at=now + timedelta(days=30),
                       revoked_at=now)          # already revoked
    db.add(sub); db.commit()
    db.add(Enrollment(tenant_id=1, user_id=user.id, course_id=course.id,
                      source="subscription", subscription_id=None,
                      expires_at=now + timedelta(days=30),
                      grant_reason=f"Auto-enrolled via subscription #{sub.id}"))
    db.commit()
    assert course.id not in _my_course_ids(client, user)


def test_untick_course_from_plan_removes_derived_access(client, db, admin, user, course):
    """The user's own experiment: removing the course from the plan now
    actually removes subscription-derived access on next read."""
    plan_id = _mk_plan(client, admin, [course.id], "lc-untick")
    body = _grant(client, admin, user.id, plan_id)
    assert course.id in _my_course_ids(client, user)

    r = client.patch(f"{PLANS}/{plan_id}",
                     headers=auth_header(client, admin.email),
                     json={"course_ids": []})
    assert r.status_code == 200, r.text
    # Untick means untick: subscription-derived access is gone on the
    # very next read, even though the sub itself is still live. The
    # enrollment ROW survives (progress preserved; re-tick restores).
    assert course.id not in _my_course_ids(client, user)
    # New subscriber of the same plan gains nothing post-untick either:
    from app.core.security import hash_password
    from app.models.user import User as U, UserRole
    u2 = U(email="untick2@example.com", name="U2", role=UserRole.USER,
           password_hash=hash_password("password123"))
    db.add(u2); db.commit(); db.refresh(u2)
    _grant(client, admin, u2.id, plan_id)
    assert course.id not in _my_course_ids(client, u2)


# ------------------------------------------------------------- expiry side

def test_subscription_expiry_removes_access(client, db, admin, user, course):
    plan_id = _mk_plan(client, admin, [course.id], "lc-subexp")
    body = _grant(client, admin, user.id, plan_id, days=30)
    assert course.id in _my_course_ids(client, user)
    # time-travel: sub + enrollment both past expiry
    sub = db.get(Subscription, body["id"])
    sub.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.query(Enrollment).filter_by(subscription_id=sub.id).update(
        {Enrollment.expires_at: sub.expires_at})
    db.commit()
    assert course.id not in _my_course_ids(client, user)


def test_admin_grant_expiry_is_enforced(client, db, admin, user, course):
    """expires_at on a direct admin enrollment was written-but-never-read;
    now it gates access."""
    r = client.post(
        f"/api/v1/admin/courses/{course.id}/enrollments",
        headers=auth_header(client, admin.email),
        json={"user_id": user.id, "grant_reason": "temp access",
              "expires_at": (datetime.now(timezone.utc)
                             - timedelta(hours=1)).isoformat()},
    )
    assert r.status_code == 201, r.text
    assert course.id not in _my_course_ids(client, user)


def test_extend_subscription_extends_derived_access(client, db, admin, user, course):
    plan_id = _mk_plan(client, admin, [course.id], "lc-extend")
    body = _grant(client, admin, user.id, plan_id, days=30)
    r = client.post(EXTEND.format(sid=body["id"]),
                    headers=auth_header(client, admin.email),
                    json={"days": 60, "reason": "gateway delay comp"})
    assert r.status_code == 200, r.text
    e = db.query(Enrollment).filter_by(subscription_id=body["id"]).first()
    db.refresh(e)
    sub = db.get(Subscription, body["id"])
    assert e.expires_at == sub.expires_at


# ------------------------------------------------------------- admin listing

def test_course_enrollments_listing_carries_identity_and_state(
        client, db, admin, user, course):
    plan_id = _mk_plan(client, admin, [course.id], "lc-listing")
    body = _grant(client, admin, user.id, plan_id)
    r = client.get(f"/api/v1/admin/courses/{course.id}/enrollments",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    row = next(x for x in r.json() if x["user_id"] == user.id)
    assert row["user_email"] == user.email
    assert row["backing_subscription_status"] == "live"
    assert row["grants_access_now"] is True

    client.post(REVOKE.format(sid=body["id"]),
                headers=auth_header(client, admin.email),
                json={"reason": "test"})
    r = client.get(
        f"/api/v1/admin/courses/{course.id}/enrollments?include_revoked=true",
        headers=auth_header(client, admin.email))
    row = next(x for x in r.json() if x["user_id"] == user.id)
    assert row["grants_access_now"] is False


def test_effective_access_endpoint(client, db, admin, user, course):
    plan_id = _mk_plan(client, admin, [course.id], "lc-effective")
    _grant(client, admin, user.id, plan_id)
    r = client.get(f"/api/v1/admin/users/{user.id}/effective-access",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(s["plan_id"] == plan_id for s in body["live_subscriptions"])
    assert any(c["course_id"] == course.id and c["grants_access_now"]
               for c in body["courses"])


# ------------------------------------------------------------- contacts dedupe

def test_contacts_known_visitors_dedupe_across_signin_states(client, db, admin, user):
    """One human, three shapes of event (signed-in, signed-out linked
    browser A, signed-out linked browser B) → ONE known visitor."""
    now = datetime.now(timezone.utc)
    linked = now - timedelta(days=2)
    for anon in ("browser-a", "browser-b"):
        db.add(AnonIdentityLink(anon_id=anon, user_id=user.id,
                                linked_at=linked))
    db.add_all([
        JourneyEvent(user_id=user.id, anon_id=None, event="page.view",
                     created_at=now - timedelta(hours=3)),
        JourneyEvent(user_id=None, anon_id="browser-a", event="page.view",
                     created_at=now - timedelta(hours=2)),
        JourneyEvent(user_id=None, anon_id="browser-b", event="page.view",
                     created_at=now - timedelta(hours=1)),
        JourneyEvent(user_id=None, anon_id="stranger", event="page.view",
                     created_at=now - timedelta(hours=1)),
    ])
    db.commit()
    r = client.get("/api/v1/admin/anonymous-traffic/summary?window=7d",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    totals = r.json()["totals"]
    # 2 = the admin (their login emits a journey event) + ONE deduped
    # user. Pre-fix this read 4: u:user, a:browser-a, a:browser-b all
    # counted separately.
    assert totals["known_users"] == 2, totals
    assert totals["anonymous"] == 1, totals


def test_two_plans_bundling_same_course_dont_409_dashboard(client, db, admin, user, course):
    """Prod incident 2026-09-07 (Ketan): two ACTIVE plans bundling the
    SAME course made /lms/me/enrollments insert two implicit enrollments
    in one flush → partial-unique violation → 409 → the dashboard showed
    "Couldn't load your courses" on every load, while direct course URLs
    worked fine. The listing must dedupe per course and return 200."""
    plan_a = _mk_plan(client, admin, [course.id], "lc-twin-a")
    plan_b = _mk_plan(client, admin, [course.id], "lc-twin-b")
    _grant(client, admin, user.id, plan_a)
    _grant(client, admin, user.id, plan_b)

    r = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    assert r.status_code == 200, r.text
    ids = [e["course_id"] for e in r.json()]
    assert ids.count(course.id) == 1

    # The killer shape: the enrollment rows get revoked (admin cleanup)
    # while BOTH subs stay active. The next dashboard load re-creates the
    # implicit enrollment — once per bundling plan, in one flush — and
    # the partial-unique index (user, course) WHERE revoked_at IS NULL
    # blows up → 409 on EVERY load until the data is untangled.
    db.query(Enrollment).filter_by(user_id=user.id, course_id=course.id)       .update({"revoked_at": datetime.now(timezone.utc)})
    db.commit()

    r = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    assert r.status_code == 200, r.text
    ids = [e["course_id"] for e in r.json()]
    assert ids.count(course.id) == 1
