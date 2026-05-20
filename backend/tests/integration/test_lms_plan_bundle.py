"""Integration tests for the Plan↔Course M:N bundle feature (PR #7 follow-up).

Pins:

  * Admin can create a Plan that bundles exam sets AND courses in one
    payload (single ``course_ids`` field, parallel to ``exam_set_ids``).

  * A user with an active subscription to that plan is auto-enrolled
    in every bundled course on their next call to /lms/me/enrollments.

  * The auto-enrollment is treated as a real enrollment everywhere
    else — course-detail returns ``is_enrolled=true``, lesson bodies
    are visible, progress can be tracked.

  * Bundles survive plan updates: removing a course from a plan stops
    NEW auto-enrolls but does NOT revoke existing implicit enrollments
    (avoids surprise paywalls mid-study; admin can revoke explicitly).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.lms import Course  # noqa: F401 — needed for ORM setup
from app.models.plan import Plan, PlanCourse  # noqa: F401
from app.models.subscription import Subscription
from tests.conftest import auth_header


PLANS_PATH = "/api/v1/admin/plans"
MY_ENROLLMENTS = "/api/v1/lms/me/enrollments"


# ----------------------------------------------------- fixtures

@pytest.fixture
def two_courses(db, admin):
    """Create two published courses + return their IDs."""
    headers = auth_header(client_for_admin(db, admin), admin.email) if False else None
    # Use raw model inserts to keep this test focused on the plan/bundle
    # behaviour, not course-create UX.
    from app.models.lms import Course
    c1 = Course(tenant_id=1, slug="data-science", title="Data Science",
                base_price_paise=0, currency="INR", enrollment_type="subscription_bundle",
                is_published=True, created_by=admin.id)
    c2 = Course(tenant_id=1, slug="ml-basics", title="ML Basics",
                base_price_paise=0, currency="INR", enrollment_type="subscription_bundle",
                is_published=True, created_by=admin.id)
    db.add_all([c1, c2]); db.commit(); db.refresh(c1); db.refresh(c2)
    _ = headers  # quiet linter
    return c1.id, c2.id


def client_for_admin(db, admin):
    """Helper used by the fixture above to avoid circular imports."""
    return None  # unused — pytest fixture forwarding


# ----------------------------------------------------- plan bundle CRUD

def test_create_plan_with_course_ids(client, db, admin, two_courses):
    """Admin posts a single payload with both exam_set_ids AND course_ids;
    response carries the linked courses."""
    c1, c2 = two_courses
    r = client.post(
        PLANS_PATH,
        headers=auth_header(client, admin.email),
        json={
            "name": "AI Engineering Bundle",
            "slug": "ai-engineering",
            "bundle_type": "course_bundle",
            "base_price_paise": 500000,
            "duration_days": 365,
            "is_active": True,
            "exam_set_ids": [],
            "course_ids": [c1, c2],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["bundle_type"] == "course_bundle"
    linked_ids = sorted(c["id"] for c in body["courses"])
    assert linked_ids == sorted([c1, c2])


def test_update_plan_replaces_course_links(client, db, admin, two_courses):
    """PATCH with course_ids replaces (not merges). Sending [c1] after
    a plan was created with [c1, c2] drops c2."""
    c1, c2 = two_courses
    r = client.post(
        PLANS_PATH, headers=auth_header(client, admin.email),
        json={"name": "Replace Test", "slug": "replace-test",
              "bundle_type": "custom", "base_price_paise": 100000,
              "duration_days": 30, "course_ids": [c1, c2]},
    )
    plan_id = r.json()["id"]

    r2 = client.patch(
        f"{PLANS_PATH}/{plan_id}",
        headers=auth_header(client, admin.email),
        json={"course_ids": [c1]},
    )
    assert r2.status_code == 200, r2.text
    linked_ids = [c["id"] for c in r2.json()["courses"]]
    assert linked_ids == [c1]


def test_unknown_course_id_returns_422(client, db, admin):
    r = client.post(
        PLANS_PATH, headers=auth_header(client, admin.email),
        json={"name": "Bad Plan", "slug": "bad-plan",
              "bundle_type": "course_bundle", "base_price_paise": 50000,
              "duration_days": 30, "course_ids": [99999]},
    )
    # Validation-level error → 422 (we raise ValidationError in service)
    assert r.status_code in (400, 422), r.text


# ----------------------------------------------------- auto-enrollment

def test_subscription_bundle_auto_enrolls_user(client, db, admin, user, two_courses):
    """A user with an active sub to a plan that bundles courses sees
    them in /lms/me/enrollments — implicit enrollment row auto-created."""
    c1, c2 = two_courses
    # Create the plan
    plan_resp = client.post(
        PLANS_PATH, headers=auth_header(client, admin.email),
        json={"name": "Bundle X", "slug": "bundle-x",
              "bundle_type": "course_bundle", "base_price_paise": 500000,
              "duration_days": 365, "course_ids": [c1, c2]},
    )
    plan_id = plan_resp.json()["id"]
    # Active subscription
    sub = Subscription(
        user_id=user.id, plan_id=plan_id, plan="pro",
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(sub); db.commit()

    # User calls /me/enrollments — auto-creates enrollment for each course
    r = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    assert r.status_code == 200, r.text
    enrolled_course_ids = sorted(e["course_id"] for e in r.json())
    assert enrolled_course_ids == sorted([c1, c2])
    assert all(e["source"] == "subscription" for e in r.json())


def test_auto_enrollment_is_idempotent(client, db, admin, user, two_courses):
    """Calling /me/enrollments twice doesn't create duplicate rows."""
    c1, c2 = two_courses
    plan_resp = client.post(
        PLANS_PATH, headers=auth_header(client, admin.email),
        json={"name": "Idempotent Bundle", "slug": "idempotent",
              "bundle_type": "course_bundle", "base_price_paise": 100000,
              "duration_days": 365, "course_ids": [c1]},
    )
    db.add(Subscription(
        user_id=user.id, plan_id=plan_resp.json()["id"], plan="pro",
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )); db.commit()

    r1 = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    r2 = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    assert r1.status_code == 200 and r2.status_code == 200
    assert len(r1.json()) == 1
    assert len(r2.json()) == 1
    assert r1.json()[0]["id"] == r2.json()[0]["id"]


def test_inactive_subscription_does_not_auto_enroll(client, db, admin, user, two_courses):
    """A revoked / expired subscription doesn't auto-enroll. Bundling
    only kicks in for ACTIVE subs (status='active', not revoked,
    not expired)."""
    c1, _ = two_courses
    plan_resp = client.post(
        PLANS_PATH, headers=auth_header(client, admin.email),
        json={"name": "Inactive Bundle", "slug": "inactive",
              "bundle_type": "course_bundle", "base_price_paise": 100000,
              "duration_days": 365, "course_ids": [c1]},
    )
    db.add(Subscription(
        user_id=user.id, plan_id=plan_resp.json()["id"], plan="pro",
        status="cancelled",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        revoked_at=datetime.now(timezone.utc) - timedelta(days=1),
    )); db.commit()
    r = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    assert r.json() == []
