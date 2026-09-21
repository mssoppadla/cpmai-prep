"""Programs — a course that wraps other courses (migration 0054).

Access to included courses is DERIVED from a live enrollment on the
program (bought / granted / free / via a plan that bundles the
program), materialised as ``source='program'`` rows on read and
re-validated every time. Covered here:

  * admin: set/replace the included list, one-level nesting rules;
  * learner: enrolling in the program opens every child (detail page,
    dashboard nests children under the program card, no duplicates);
  * lifecycle: revoke program → derived rows die, a separately bought
    child survives; removing a child from the program drops it;
  * plans: a plan that bundles the PROGRAM grants the children;
  * regression: a dead enrollment row (expired grant) on a child must
    never block access the program now provides.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.lms import Course, Enrollment
from app.models.subscription import Subscription
from tests.conftest import auth_header

COURSES = "/api/v1/admin/courses"
PLANS = "/api/v1/admin/plans"
MY_ENROLLMENTS = "/api/v1/lms/me/enrollments"
PUBLIC_COURSE = "/api/v1/lms/courses/{slug}"


# ----------------------------------------------------- fixtures / helpers

@pytest.fixture
def program_setup(db, admin):
    """A program + two published child courses + one unrelated course."""
    def mk(slug, title, **kw):
        c = Course(tenant_id=1, slug=slug, title=title, base_price_paise=0,
                   currency="INR", enrollment_type="paid", is_published=True,
                   created_by=admin.id, **kw)
        db.add(c)
        return c
    prog = mk("ai-mastery", "AI Mastery Program", is_program=True)
    c1 = mk("data-prep", "Data Preparation")
    c2 = mk("model-ops", "Model Operations")
    other = mk("solo", "Standalone Course")
    db.commit()
    for c in (prog, c1, c2, other):
        db.refresh(c)
    return prog, c1, c2, other


def _set_children(client, admin, program_id, course_ids, expect=200):
    r = client.put(f"{COURSES}/{program_id}/program-courses",
                   headers=auth_header(client, admin.email),
                   json={"courses": [{"course_id": cid} for cid in course_ids]})
    assert r.status_code == expect, r.text
    return r


def _grant(client, admin, course_id, user_id):
    r = client.post(f"{COURSES}/{course_id}/enrollments",
                    headers=auth_header(client, admin.email),
                    json={"user_id": user_id, "grant_reason": "test"})
    assert r.status_code == 201, r.text
    return r.json()


def _my(client, user):
    r = client.get(MY_ENROLLMENTS, headers=auth_header(client, user.email))
    assert r.status_code == 200, r.text
    return r.json()


def _detail(client, user, slug):
    r = client.get(PUBLIC_COURSE.format(slug=slug),
                   headers=auth_header(client, user.email))
    return r


# ----------------------------------------------------- admin rules

def test_set_program_courses_orders_and_replaces(client, db, admin, program_setup):
    prog, c1, c2, other = program_setup
    body = _set_children(client, admin, prog.id, [c2.id, c1.id]).json()
    assert [b["course_id"] for b in body] == [c2.id, c1.id]
    assert [b["position"] for b in body] == [0, 1]
    assert body[0]["title"] == "Model Operations"
    # replace: drops c2, keeps c1, adds other
    body = _set_children(client, admin, prog.id, [c1.id, other.id]).json()
    assert [b["course_id"] for b in body] == [c1.id, other.id]
    r = client.get(f"{COURSES}/{prog.id}/program-courses",
                   headers=auth_header(client, admin.email))
    assert [b["course_id"] for b in r.json()] == [c1.id, other.id]


def test_program_nesting_is_one_level(client, db, admin, program_setup):
    prog, c1, c2, other = program_setup
    other.is_program = True; db.commit()
    # a program can't include another program
    _set_children(client, admin, prog.id, [c1.id, other.id], expect=422)
    # ... nor itself, nor a course twice
    _set_children(client, admin, prog.id, [prog.id], expect=422)
    _set_children(client, admin, prog.id, [c1.id, c1.id], expect=422)
    # a child can't be turned into a program while it is included
    _set_children(client, admin, prog.id, [c1.id])
    r = client.patch(f"{COURSES}/{c1.id}", headers=auth_header(client, admin.email),
                     json={"is_program": True})
    assert r.status_code == 422, r.text
    # non-program courses have no included list
    r = client.put(f"{COURSES}/{c1.id}/program-courses",
                   headers=auth_header(client, admin.email), json={"courses": []})
    assert r.status_code == 422


# ----------------------------------------------------- learner access

def test_program_enrollment_opens_children_and_nests_them(
        client, db, admin, user, program_setup):
    prog, c1, c2, other = program_setup
    _set_children(client, admin, prog.id, [c1.id, c2.id])
    _grant(client, admin, prog.id, user.id)

    # Detail of a child: enrolled, via the program
    r = _detail(client, user, c1.slug)
    assert r.status_code == 200 and r.json()["is_enrolled"] is True
    # ... and of the unrelated course: not enrolled
    assert _detail(client, user, other.slug).json()["is_enrolled"] is False

    # Program detail lists children with per-child enrollment state
    body = _detail(client, user, prog.slug).json()
    assert body["is_enrolled"] is True
    assert [pc["course"]["slug"] for pc in body["program_courses"]] == [c1.slug, c2.slug]
    assert all(pc["is_enrolled"] for pc in body["program_courses"])

    # Dashboard: ONE program card, children nested, no duplicate cards
    mine = _my(client, user)
    assert [m["course_id"] for m in mine] == [prog.id]
    card = mine[0]
    assert card["is_program"] is True
    assert [k["course_id"] for k in card["program_children"]] == [c1.id, c2.id]

    # Derived rows exist and are program-sourced
    rows = db.query(Enrollment).filter(Enrollment.user_id == user.id,
                                       Enrollment.revoked_at.is_(None)).all()
    by_course = {e.course_id: e for e in rows}
    assert by_course[c1.id].source == "program"
    assert by_course[c2.id].source == "program"
    assert by_course[prog.id].source == "admin_grant"


def test_separately_bought_child_shows_once_and_survives_program_revoke(
        client, db, admin, user, program_setup):
    prog, c1, c2, other = program_setup
    _set_children(client, admin, prog.id, [c1.id, c2.id])
    # user already owns c1 outright
    own = _grant(client, admin, c1.id, user.id)
    prog_enr = _grant(client, admin, prog.id, user.id)

    mine = _my(client, user)
    assert [m["course_id"] for m in mine] == [prog.id]          # c1 shown once, nested
    assert {k["course_id"] for k in mine[0]["program_children"]} == {c1.id, c2.id}
    # the outright grant on c1 was NOT converted to a derived row
    e1 = db.get(Enrollment, own["id"]); db.refresh(e1)
    assert e1.source == "admin_grant" and e1.revoked_at is None

    # Revoke the program → c2 access gone, c1 still owned, shown as its own card
    r = client.delete(f"/api/v1/admin/enrollments/{prog_enr['id']}",
                      headers=auth_header(client, admin.email))
    assert r.status_code == 204
    assert _detail(client, user, c2.slug).json()["is_enrolled"] is False
    assert _detail(client, user, c1.slug).json()["is_enrolled"] is True
    mine = _my(client, user)
    assert [m["course_id"] for m in mine] == [c1.id]
    assert mine[0]["is_program"] is False


def test_removing_child_from_program_drops_derived_access(
        client, db, admin, user, program_setup):
    prog, c1, c2, other = program_setup
    _set_children(client, admin, prog.id, [c1.id, c2.id])
    _grant(client, admin, prog.id, user.id)
    assert _detail(client, user, c2.slug).json()["is_enrolled"] is True
    _set_children(client, admin, prog.id, [c1.id])
    assert _detail(client, user, c2.slug).json()["is_enrolled"] is False
    assert _detail(client, user, c1.slug).json()["is_enrolled"] is True
    mine = _my(client, user)
    assert [k["course_id"] for k in mine[0]["program_children"]] == [c1.id]


def test_plan_bundling_a_program_grants_its_children(
        client, db, admin, user, program_setup):
    prog, c1, c2, other = program_setup
    _set_children(client, admin, prog.id, [c1.id, c2.id])
    r = client.post(PLANS, headers=auth_header(client, admin.email),
                    json={"name": "Program plan", "slug": "program-plan",
                          "bundle_type": "course_bundle", "base_price_paise": 1000,
                          "duration_days": 365, "course_ids": [prog.id]})
    assert r.status_code == 201, r.text
    sub = Subscription(user_id=user.id, plan_id=r.json()["id"], plan="pro",
                       status="active",
                       expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    db.add(sub); db.commit()

    # Child page directly (no dashboard visit first): access derives
    # through program ← subscription in one read.
    assert _detail(client, user, c1.slug).json()["is_enrolled"] is True
    mine = _my(client, user)
    assert [m["course_id"] for m in mine] == [prog.id]
    assert mine[0]["source"] == "subscription"
    assert {k["course_id"] for k in mine[0]["program_children"]} == {c1.id, c2.id}

    # Subscription lapses → everything derived goes
    sub.revoked_at = datetime.now(timezone.utc); sub.status = "cancelled"; db.commit()
    assert _detail(client, user, c1.slug).json()["is_enrolled"] is False
    assert _my(client, user) == []


def test_program_children_visible_to_anonymous_but_locked(client, db, admin, program_setup):
    prog, c1, c2, other = program_setup
    c2.is_published = False; db.commit()          # internal child
    _set_children(client, admin, prog.id, [c1.id, c2.id])
    r = client.get(PUBLIC_COURSE.format(slug=prog.slug))
    assert r.status_code == 200
    body = r.json()
    assert body["is_enrolled"] is False
    # unpublished child hidden from non-enrollees; published one listed
    assert [pc["course"]["slug"] for pc in body["program_courses"]] == [c1.slug]
    assert body["course"]["is_program"] is True


def test_unpublished_child_reachable_through_program(client, db, admin, user, program_setup):
    """An internal (draft) child behaves like an internal course: hidden
    from the catalog, open to the program's enrollees."""
    prog, c1, c2, other = program_setup
    c2.is_published = False; db.commit()
    _set_children(client, admin, prog.id, [c1.id, c2.id])
    assert _detail(client, user, c2.slug).status_code == 404
    _grant(client, admin, prog.id, user.id)
    r = _detail(client, user, c2.slug)
    assert r.status_code == 200 and r.json()["is_enrolled"] is True
    # catalog still doesn't list it
    r = client.get("/api/v1/lms/courses")
    assert c2.slug not in {c["slug"] for c in r.json()}
    prog_card = next(c for c in r.json() if c["slug"] == prog.slug)
    assert prog_card["program_course_count"] == 2


# ----------------------------------------------------- regression: dead rows

def test_dead_child_row_does_not_block_program_access(
        client, db, admin, user, program_setup):
    """Incident class: a stale un-revoked enrollment row (here an expired
    admin grant) used to satisfy the (user, course) uniqueness and block
    the implicit row, locking the learner out of a course a live
    entitlement covered. The dead row is re-pointed instead."""
    prog, c1, c2, other = program_setup
    _set_children(client, admin, prog.id, [c1.id])
    dead = Enrollment(tenant_id=1, user_id=user.id, course_id=c1.id,
                      source="admin_grant", grant_reason="old",
                      expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    db.add(dead); db.commit(); db.refresh(dead)
    assert _detail(client, user, c1.slug).json()["is_enrolled"] is False
    _grant(client, admin, prog.id, user.id)
    assert _detail(client, user, c1.slug).json()["is_enrolled"] is True
    db.refresh(dead)
    assert dead.source == "program" and dead.expires_at is None
    mine = _my(client, user)
    assert [k["course_id"] for k in mine[0]["program_children"]] == [c1.id]


def test_dead_row_does_not_block_subscription_access(client, db, admin, user, program_setup):
    """Same incident class for plain plan bundles: expired grant on a
    course + a live plan that bundles it → access, not a lock-out."""
    _, c1, _, _ = program_setup
    r = client.post(PLANS, headers=auth_header(client, admin.email),
                    json={"name": "P", "slug": "p-bundle", "bundle_type": "course_bundle",
                          "base_price_paise": 1000, "duration_days": 365,
                          "course_ids": [c1.id]})
    dead = Enrollment(tenant_id=1, user_id=user.id, course_id=c1.id,
                      source="admin_grant", grant_reason="old",
                      expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    db.add(dead)
    db.add(Subscription(user_id=user.id, plan_id=r.json()["id"], plan="pro",
                        status="active",
                        expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
    db.commit()
    assert _detail(client, user, c1.slug).json()["is_enrolled"] is True
    assert [m["course_id"] for m in _my(client, user)] == [c1.id]
    db.refresh(dead)
    assert dead.source == "subscription"
