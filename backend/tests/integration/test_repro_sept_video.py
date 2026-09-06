"""Prod repro (2026-09-06): active live-class sub + plan bundles a DRAFT
course, yet /lms/me/enrollments does not enroll two specific users while
it did enroll two others. Mirrors the exact prod shapes to find the
discriminating variable. Diagnostic first; keep as regression pins.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.lms import Course, Enrollment
from app.models.subscription import Subscription
from tests.conftest import auth_header

PLANS_PATH = "/api/v1/admin/plans"
MY_ENROLLMENTS = "/api/v1/lms/me/enrollments"
GRANT = "/api/v1/admin/users/{uid}/subscriptions"


@pytest.fixture
def draft_course(db, admin):
    """Mirror sept-2026: unpublished, subscription_bundle, not deleted."""
    c = Course(tenant_id=1, slug="sept-2026", title="Live Recording: Batch-Sept 2026",
               base_price_paise=0, currency="INR",
               enrollment_type="subscription_bundle",
               is_published=False, created_by=admin.id)
    db.add(c); db.commit(); db.refresh(c)
    return c


def _mk_plan(client, admin, course_ids, slug="live-class-x"):
    r = client.post(
        PLANS_PATH, headers=auth_header(client, admin.email),
        json={"name": f"Plan {slug}", "slug": slug, "bundle_type": "custom",
              "base_price_paise": 1270000, "duration_days": 365,
              "is_active": True, "course_ids": course_ids},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_draft_course_admin_grant_auto_enrolls(client, db, admin, user, draft_course):
    """T1 — the basic prod shape: DRAFT bundled course + manual admin
    grant via the real endpoint (not a raw model insert)."""
    plan_id = _mk_plan(client, admin, [draft_course.id])
    r = client.post(
        GRANT.format(uid=user.id), headers=auth_header(client, admin.email),
        json={"plan_id": plan_id, "period_days": 30, "reason": "prod repro"},
    )
    assert r.status_code == 201, r.text

    r = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    assert r.status_code == 200, r.text
    ids = [e["course_id"] for e in r.json()]
    assert draft_course.id in ids, (
        f"draft bundled course missing from enrollments: {r.json()}")


def test_ketan_shape_revoked_and_active_same_plan(client, db, admin, user, draft_course):
    """T2 — Ketan's exact sub mix: several REVOKED subs of the same plan
    plus one active one, plus an unrelated active plan with no courses."""
    plan_id = _mk_plan(client, admin, [draft_course.id], slug="live-class-y")
    other_plan_id = _mk_plan(client, admin, [], slug="exam-bundle-y")
    now = datetime.now(timezone.utc)
    for i in range(3):  # the #54/#55/#56 pile
        db.add(Subscription(
            user_id=user.id, plan="live-class-y", plan_id=plan_id,
            status="active", expires_at=now + timedelta(days=30),
            revoked_at=now - timedelta(hours=1),
        ))
    db.add(Subscription(  # the surviving #58
        user_id=user.id, plan="live-class-y", plan_id=plan_id,
        status="active", expires_at=now + timedelta(days=30),
    ))
    db.add(Subscription(  # unrelated active exam-bundle (#25)
        user_id=user.id, plan="exam-bundle-y", plan_id=other_plan_id,
        status="active", expires_at=now + timedelta(days=300),
    ))
    db.commit()

    r = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    assert r.status_code == 200, r.text
    ids = [e["course_id"] for e in r.json()]
    assert draft_course.id in ids, (
        f"Ketan-shape user not enrolled: {r.json()}")


def test_link_added_after_grant_then_next_visit_enrolls(client, db, admin, user, draft_course):
    """T3 — the prod timeline: grant FIRST, link the course to the plan
    LATER, then the user visits. The sweep must pick it up (no
    'first-column snapshot' of the plan at grant time)."""
    plan_id = _mk_plan(client, admin, [], slug="live-class-z")  # no courses yet
    r = client.post(
        GRANT.format(uid=user.id), headers=auth_header(client, admin.email),
        json={"plan_id": plan_id, "period_days": 30, "reason": "prod repro"},
    )
    assert r.status_code == 201, r.text

    # first visit: nothing bundled yet
    r = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    assert all(e["course_id"] != draft_course.id for e in r.json())

    # admin links the course afterwards (the re-tick)
    r = client.patch(
        f"{PLANS_PATH}/{plan_id}", headers=auth_header(client, admin.email),
        json={"course_ids": [draft_course.id]},
    )
    assert r.status_code == 200, r.text

    # next visit: must enroll now
    r = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    ids = [e["course_id"] for e in r.json()]
    assert draft_course.id in ids, (
        f"link-after-grant not picked up on next visit: {r.json()}")
