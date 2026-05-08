"""Paywall on premium exam-set attempt-start.

Free sets stay open. Premium sets need either a legacy "any-active"
subscription or a Plan-based subscription whose Plan includes that
exam set.
"""
from datetime import datetime, timedelta, timezone
import pytest
from app.models.plan import Plan, PlanExamSet
from app.models.exam_set import ExamSet, ExamSetQuestion
from app.models.subscription import Subscription
from tests.conftest import auth_header


def _make_premium_set(db, slug, admin, sample_question) -> ExamSet:
    es = ExamSet(name=f"Premium {slug}", slug=slug,
                 description="Paid-only exam.", time_limit_minutes=30,
                 passing_score=70, is_active=True, is_premium=True,
                 created_by=admin.id)
    db.add(es); db.flush()
    db.add(ExamSetQuestion(exam_set_id=es.id, question_id=sample_question.id,
                            position=10, added_by=admin.id))
    db.commit(); db.refresh(es)
    return es


def _make_plan_with(db, *, slug, exam_set_id, admin) -> Plan:
    p = Plan(name=f"Plan {slug}", slug=slug, bundle_type="exam_bundle",
             base_price_paise=10_000, currency="INR", duration_days=365,
             perks={}, is_active=True, display_order=10,
             created_by=admin.id)
    db.add(p); db.flush()
    db.add(PlanExamSet(plan_id=p.id, exam_set_id=exam_set_id,
                        added_by=admin.id))
    db.commit(); db.refresh(p)
    return p


# ======================================================= legacy compat
def test_user_with_legacy_active_sub_can_start_premium(
        client, db, user, admin, sample_question):
    es = _make_premium_set(db, "premium-1", admin, sample_question)
    db.add(Subscription(user_id=user.id, plan="pro", status="active"))
    db.commit()
    r = client.post(f"/api/v1/exam-sets/{es.slug}/start",
                    headers=auth_header(client, user.email))
    assert r.status_code == 201, r.text


# ======================================================= plan-based access
def test_user_with_plan_covering_set_can_start(
        client, db, user, admin, sample_question):
    es = _make_premium_set(db, "premium-2", admin, sample_question)
    plan = _make_plan_with(db, slug="bundle-a", exam_set_id=es.id, admin=admin)
    sub = Subscription(user_id=user.id, plan=plan.slug, plan_id=plan.id,
                        status="active",
                        expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    db.add(sub); db.commit()
    r = client.post(f"/api/v1/exam-sets/{es.slug}/start",
                    headers=auth_header(client, user.email))
    assert r.status_code == 201, r.text


def test_user_with_plan_not_covering_set_blocked(
        client, db, user, admin, sample_question, sample_exam_set):
    es = _make_premium_set(db, "premium-3", admin, sample_question)
    # Plan covers a DIFFERENT exam set, not `es`.
    other_plan = _make_plan_with(db, slug="bundle-other",
                                  exam_set_id=sample_exam_set.id, admin=admin)
    sub = Subscription(user_id=user.id, plan=other_plan.slug,
                        plan_id=other_plan.id, status="active",
                        expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    db.add(sub); db.commit()
    r = client.post(f"/api/v1/exam-sets/{es.slug}/start",
                    headers=auth_header(client, user.email))
    assert r.status_code == 402   # SubscriptionRequiredError


def test_expired_plan_sub_blocks(client, db, user, admin, sample_question):
    es = _make_premium_set(db, "premium-4", admin, sample_question)
    plan = _make_plan_with(db, slug="bundle-x", exam_set_id=es.id, admin=admin)
    sub = Subscription(user_id=user.id, plan=plan.slug, plan_id=plan.id,
                        status="active",
                        expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    db.add(sub); db.commit()
    r = client.post(f"/api/v1/exam-sets/{es.slug}/start",
                    headers=auth_header(client, user.email))
    assert r.status_code == 402


def test_no_subscription_blocks(client, db, user, admin, sample_question):
    es = _make_premium_set(db, "premium-5", admin, sample_question)
    r = client.post(f"/api/v1/exam-sets/{es.slug}/start",
                    headers=auth_header(client, user.email))
    assert r.status_code == 402


def test_free_set_open_to_authenticated_user(
        client, db, user, sample_exam_set):
    # sample_exam_set is is_premium=False by default.
    r = client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start",
                    headers=auth_header(client, user.email))
    assert r.status_code == 201, r.text
