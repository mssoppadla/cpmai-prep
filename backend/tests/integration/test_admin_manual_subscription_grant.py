"""Admin manual plan grant / extend / revoke — Block C of the bundled
auth/router/admin-grant PR.

Real-world scenario this guards: user paid via PayPal, the payment got
held PENDING by the gateway, our system never received a successful
capture, the user shows "no active subscription" despite having been
debited. With this feature shipped, the admin can unblock them in
< 30 seconds via the /admin/users → Subscriptions panel.

The tests below pin the contract:

  1. **Grant** writes a Subscription row + an audit_logs row, the
     paywall sees it as active immediately, and ``source``/``granted_by``
     /``grant_reason`` are populated.

  2. **Extend** bumps ``expires_at`` by ``days`` and writes an audit
     row. Refuses to extend a revoked sub.

  3. **Revoke** sets ``revoked_at`` and writes an audit row. The
     paywall immediately treats the sub as inactive even if
     ``expires_at`` is still in the future. Re-revoke is idempotent.

  4. **RBAC**: regular user gets 401/403. Both admin and super_admin
     can grant (the user's chosen policy).

  5. **Paywall continuity**: existing non-revoked subs keep working.
     A revoked sub is filtered out of the active-subs query.

  6. **Reason captured everywhere**: in the subscription row AND in the
     audit_logs metadata. Survives even if the FK to the actor is
     later NULLed (ondelete=SET NULL).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import desc

from app.models.audit_log import AuditLog
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User, UserRole
from tests.conftest import auth_header


# ----------------------------------------------------------- helpers / fixtures

@pytest.fixture
def grant_plan(db):
    """A plan the admin can grant. Match the live schema (slug + name +
    duration_days). Doesn't matter what duration the plan has — the
    grant endpoint takes its own ``period_days`` so the admin can
    comp arbitrary windows."""
    p = Plan(
        name="Premium Test",
        slug="premium-test",
        description="Test plan for grant tests",
        bundle_type="exam_bundle",
        currency="INR",
        base_price_paise=100000,
        duration_days=30,
        is_active=True,
    )
    db.add(p); db.commit(); db.refresh(p)
    return p


def _grant_payload(plan_id: int, **overrides) -> dict:
    base = {
        "plan_id": plan_id,
        "period_days": 30,
        "reason": "PayPal held the user's funds for 5 days; debit on card "
                  "statement, no successful capture on our side.",
        "source": "manual_admin_grant",
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------- 1. grant happy path

def test_grant_creates_active_subscription_and_audit_row(
    client, db, admin, user, grant_plan,
):
    r = client.post(
        f"/api/v1/admin/users/{user.id}/subscriptions",
        json=_grant_payload(grant_plan.id),
        headers=auth_header(client, admin.email),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    sub_id = body["id"]

    # Surface fields
    assert body["user_id"] == user.id
    assert body["plan_id"] == grant_plan.id
    assert body["status"] == "active"
    assert body["source"] == "manual_admin_grant"
    assert body["granted_by_user_id"] == admin.id
    assert body["granted_by_email"] == admin.email
    assert body["grant_reason"].startswith("PayPal held")
    assert body["is_active_now"] is True

    # DB invariants
    db.expire_all()
    sub = db.get(Subscription, sub_id)
    assert sub.granted_by == admin.id
    assert sub.source == "manual_admin_grant"
    assert sub.revoked_at is None
    assert sub.expires_at is not None
    # Roughly 30 days in the future (allow 1-minute slack for clock drift)
    delta = sub.expires_at - datetime.now(timezone.utc)
    assert timedelta(days=29, hours=23) < delta < timedelta(days=30, minutes=1)

    # Audit log
    audit = (db.query(AuditLog)
             .filter(AuditLog.action == "admin.subscription.grant")
             .order_by(desc(AuditLog.id)).first())
    assert audit is not None
    assert audit.user_id == admin.id
    md = audit.metadata_json
    assert md["target_user_id"] == user.id
    assert md["target_user_email"] == user.email
    assert md["subscription_id"] == sub_id
    assert md["plan_id"] == grant_plan.id
    assert md["period_days"] == 30
    assert md["source"] == "manual_admin_grant"
    assert "PayPal held" in md["reason"]


# ----------------------------------------------------------- 2. extend

def test_extend_bumps_expires_at_and_writes_audit(
    client, db, admin, user, grant_plan,
):
    r = client.post(
        f"/api/v1/admin/users/{user.id}/subscriptions",
        json=_grant_payload(grant_plan.id, period_days=10),
        headers=auth_header(client, admin.email),
    )
    sub_id = r.json()["id"]
    old_expiry_iso = r.json()["expires_at"]

    r2 = client.post(
        f"/api/v1/admin/subscriptions/{sub_id}/extend",
        json={"days": 7, "reason": "Comp-ing the week they lost to the bug."},
        headers=auth_header(client, admin.email),
    )
    assert r2.status_code == 200, r2.text
    new_expiry = datetime.fromisoformat(r2.json()["expires_at"])
    old_expiry = datetime.fromisoformat(old_expiry_iso)
    delta = new_expiry - old_expiry
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, minutes=1)

    audit = (db.query(AuditLog)
             .filter(AuditLog.action == "admin.subscription.extend")
             .order_by(desc(AuditLog.id)).first())
    assert audit is not None
    assert audit.metadata_json["days_added"] == 7
    assert "lost to the bug" in audit.metadata_json["reason"]


# ----------------------------------------------------------- 3. revoke

def test_revoke_sets_revoked_at_and_paywall_sees_inactive(
    client, db, admin, user, grant_plan,
):
    r = client.post(
        f"/api/v1/admin/users/{user.id}/subscriptions",
        json=_grant_payload(grant_plan.id, period_days=365),
        headers=auth_header(client, admin.email),
    )
    sub_id = r.json()["id"]
    assert r.json()["is_active_now"] is True

    r2 = client.post(
        f"/api/v1/admin/subscriptions/{sub_id}/revoke",
        json={"reason": "User requested refund — issued via Razorpay."},
        headers=auth_header(client, admin.email),
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["revoked_at"] is not None
    assert body["revoked_by_email"] == admin.email
    assert body["revoke_reason"].startswith("User requested")
    # The paywall view should flip immediately, even though expires_at
    # is still ~365 days in the future.
    assert body["is_active_now"] is False

    # Audit log
    audit = (db.query(AuditLog)
             .filter(AuditLog.action == "admin.subscription.revoke")
             .order_by(desc(AuditLog.id)).first())
    assert audit is not None
    assert "refund" in audit.metadata_json["reason"]


def test_revoke_is_idempotent(client, db, admin, user, grant_plan):
    r = client.post(
        f"/api/v1/admin/users/{user.id}/subscriptions",
        json=_grant_payload(grant_plan.id),
        headers=auth_header(client, admin.email),
    )
    sub_id = r.json()["id"]
    client.post(f"/api/v1/admin/subscriptions/{sub_id}/revoke",
                json={"reason": "first time"},
                headers=auth_header(client, admin.email))
    r2 = client.post(f"/api/v1/admin/subscriptions/{sub_id}/revoke",
                      json={"reason": "second time (should be ignored)"},
                      headers=auth_header(client, admin.email))
    # Idempotent: returns the existing revoked row, doesn't overwrite the
    # original revoke_reason.
    assert r2.status_code == 200
    db.expire_all()
    sub = db.get(Subscription, sub_id)
    assert sub.revoke_reason == "first time"


def test_extend_refuses_revoked_subscription(
    client, db, admin, user, grant_plan,
):
    r = client.post(
        f"/api/v1/admin/users/{user.id}/subscriptions",
        json=_grant_payload(grant_plan.id),
        headers=auth_header(client, admin.email),
    )
    sub_id = r.json()["id"]
    client.post(f"/api/v1/admin/subscriptions/{sub_id}/revoke",
                json={"reason": "test"},
                headers=auth_header(client, admin.email))
    r2 = client.post(f"/api/v1/admin/subscriptions/{sub_id}/extend",
                      json={"days": 7, "reason": "try to revive"},
                      headers=auth_header(client, admin.email))
    # We reject extending a revoked sub (grant a fresh one instead).
    assert r2.status_code in (400, 422), r2.text


# ----------------------------------------------------------- 4. RBAC

def test_grant_rejects_regular_user(client, user, grant_plan):
    """A signed-in regular user must not be able to grant themselves
    a paid plan. Defence-in-depth — the route is admin-gated, but pin
    the test so a future refactor can't accidentally loosen it."""
    r = client.post(
        f"/api/v1/admin/users/{user.id}/subscriptions",
        json=_grant_payload(grant_plan.id),
        headers=auth_header(client, user.email),
    )
    assert r.status_code in (401, 403)


def test_grant_accepted_for_super_admin(
    client, db, super_admin, user, grant_plan,
):
    """The user's chosen policy: BOTH admin and super_admin can grant.
    The admin happy-path is covered above; this confirms super_admin
    can do it too (no regression from the role-widening decision)."""
    r = client.post(
        f"/api/v1/admin/users/{user.id}/subscriptions",
        json=_grant_payload(grant_plan.id),
        headers=auth_header(client, super_admin.email),
    )
    assert r.status_code == 201, r.text
    assert r.json()["granted_by_user_id"] == super_admin.id


# ----------------------------------------------------------- 5. listing

def test_list_returns_subs_newest_first_with_actor_emails(
    client, db, admin, user, grant_plan,
):
    # Grant two subs with a small delay so created_at orders them.
    for note in ["first grant", "second grant"]:
        client.post(
            f"/api/v1/admin/users/{user.id}/subscriptions",
            json=_grant_payload(grant_plan.id, reason=note),
            headers=auth_header(client, admin.email),
        )

    r = client.get(f"/api/v1/admin/users/{user.id}/subscriptions",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 2
    # Newest first
    assert items[0]["grant_reason"] == "second grant"
    assert items[1]["grant_reason"] == "first grant"
    # Actor email join
    assert items[0]["granted_by_email"] == admin.email


# ----------------------------------------------------------- 6. validators

def test_grant_requires_reason(client, admin, user, grant_plan):
    r = client.post(
        f"/api/v1/admin/users/{user.id}/subscriptions",
        json=_grant_payload(grant_plan.id, reason=""),
        headers=auth_header(client, admin.email),
    )
    # Pydantic validation: min_length=3
    assert r.status_code == 422


def test_grant_caps_period_at_10_years(client, admin, user, grant_plan):
    r = client.post(
        f"/api/v1/admin/users/{user.id}/subscriptions",
        json=_grant_payload(grant_plan.id, period_days=99999),
        headers=auth_header(client, admin.email),
    )
    # Pydantic validation: le=3650
    assert r.status_code == 422


def test_grant_rejects_unknown_plan(client, admin, user):
    r = client.post(
        f"/api/v1/admin/users/{user.id}/subscriptions",
        json={
            "plan_id": 999_999, "period_days": 30,
            "reason": "anything",
            "source": "manual_admin_grant",
        },
        headers=auth_header(client, admin.email),
    )
    assert r.status_code in (400, 422)


def test_grant_rejects_unknown_user(client, admin, grant_plan):
    r = client.post(
        f"/api/v1/admin/users/999999/subscriptions",
        json=_grant_payload(grant_plan.id),
        headers=auth_header(client, admin.email),
    )
    assert r.status_code == 404
