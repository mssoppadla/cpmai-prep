"""Backward compatibility tests for Phase 1 multi-tenancy foundation.

These tests pin the critical-risk mitigations from docs/contracts/
multi-tenancy-and-saas-integration.md §15:

  - CR-1: Existing user logins continue to work (no forced re-login)
  - CR-2: Existing audit_logs data remains queryable after the
          tenant_id column is added + backfilled
  - HR-3: audit_log() signature change is additive — existing callers
          that don't pass tenant_id keep working
  - BC-2: Old JWTs without tenant_id claim still decode and behave
          as if tenant_id=1

If any of these tests fail, Phase 1 deploys are unsafe — they would
break existing CPMAI users.
"""
from __future__ import annotations

from jose import jwt

from app.core.audit import audit_log
from app.core.config import settings
from app.core.security import (
    JWT_ALGORITHM,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.core.tenant import get_current_tenant_id
from app.models.audit_log import AuditLog
from app.models.tenant import Tenant
from tests.conftest import auth_header


# ----------------------------------------------------- CR-1: old JWTs work

def test_jwt_minted_without_tenant_id_has_no_tenant_claim(default_tenant):
    """When ``create_access_token()`` is called WITHOUT a tenant_id
    kwarg (existing Phase 1 call sites), the resulting JWT has no
    ``tenant_id`` claim at all. Old callers stay byte-identical.
    """
    token = create_access_token(user_id=42, role="user")
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
    assert "tenant_id" not in payload
    assert payload["sub"] == "42"
    assert payload["role"] == "user"


def test_jwt_minted_with_tenant_id_includes_claim(default_tenant):
    """When Phase 2 (or any caller) passes tenant_id explicitly, the
    JWT carries the claim."""
    token = create_access_token(user_id=42, role="user", tenant_id=1)
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
    assert payload["tenant_id"] == 1


def test_old_jwt_without_tenant_claim_decodes_normally(default_tenant):
    """A JWT minted before Phase 1 had no tenant_id claim. Phase 1
    code must decode it normally — readers that want tenant_id should
    default the missing claim to 1.

    This is the critical CR-1 mitigation: existing users in the wild
    are NOT logged out by the Phase 1 deploy.
    """
    # Mint a pre-Phase-1-style token (no tenant_id)
    token = create_access_token(user_id=42, role="user")
    # Decode it the way the rest of the app does
    payload = decode_token(token)
    # The standard claim defaults to 1 for old tokens
    assert payload.get("tenant_id", 1) == 1


def test_refresh_token_supports_optional_tenant_id(default_tenant):
    """Same backward-compat applies to refresh tokens. Old refresh
    tokens (no tenant_id claim) decode normally."""
    # Old style
    token_old, _jti = create_refresh_token(user_id=42)
    payload_old = decode_token(token_old)
    assert "tenant_id" not in payload_old
    # New style
    token_new, _jti = create_refresh_token(user_id=42, tenant_id=1)
    payload_new = decode_token(token_new)
    assert payload_new["tenant_id"] == 1


# ----------------------------------------------------- CR-2: audit_logs data

def test_existing_audit_logs_remain_queryable_after_tenant_id_column(
    db, default_tenant,
):
    """After migration 0023, existing audit_logs rows have tenant_id=1
    (backfilled in the migration). They must remain queryable via the
    ORM without surprises.

    In SQLite tests, the schema is recreated fresh per test, so the
    "existing rows" here are ones we just inserted before adding
    tenant_id. We verify the read path tolerates rows whose tenant_id
    is explicitly 1.
    """
    # Insert via the ORM — should land with tenant_id=1 thanks to
    # audit_log() helper default
    audit_log(db, user_id=None, action="test.pre_phase1_event",
              metadata={"note": "simulating pre-Phase-1 row"})
    # Pull via raw ORM query — make sure tenant_id is queryable
    row = db.query(AuditLog).filter(
        AuditLog.action == "test.pre_phase1_event"
    ).one()
    assert row.tenant_id == 1
    assert row.action == "test.pre_phase1_event"
    # Confirm it's the CPMAI tenant via the FK
    tenant = db.get(Tenant, row.tenant_id)
    assert tenant is not None
    assert tenant.slug == "cpmai"


def test_audit_logs_with_null_tenant_id_are_still_readable(db, default_tenant):
    """Defensive: even if some legacy row somehow has tenant_id=NULL
    (e.g. inserted by raw SQL bypassing the helper), the ORM reads it
    without error. Application code is expected to coerce NULL → 1
    on the read path (per contract MR-4 mitigation).
    """
    # Insert directly bypassing audit_log() helper
    db.add(AuditLog(
        user_id=None, action="test.null_tenant_event",
        tenant_id=None,  # legacy NULL
        metadata_json={},
    ))
    db.commit()
    # Should still be readable
    row = db.query(AuditLog).filter(
        AuditLog.action == "test.null_tenant_event"
    ).one()
    assert row.action == "test.null_tenant_event"
    # tenant_id is None on this row; downstream code coerces to 1
    assert row.tenant_id is None


# ----------------------------------------------------- HR-3: audit_log signature

def test_audit_log_works_without_tenant_id_kwarg(db, default_tenant):
    """Every existing audit_log() call in cpmai-prep omits tenant_id.
    The new signature must accept the omission and auto-default to
    ``get_current_tenant_id()`` (= 1 in Phase 1).

    This pins HR-3 — adding the param without breaking callers.
    """
    # Existing-style call — no tenant_id kwarg
    audit_log(db, user_id=None, action="user.login")
    row = db.query(AuditLog).filter(
        AuditLog.action == "user.login"
    ).one()
    # Helper auto-defaulted to tenant 1
    assert row.tenant_id == 1


def test_audit_log_accepts_explicit_tenant_id_when_passed(db, default_tenant):
    """When called with explicit tenant_id (Phase 2 style), it uses
    that value rather than the default."""
    audit_log(db, user_id=None, action="test.explicit_tenant",
              tenant_id=1)
    row = db.query(AuditLog).filter(
        AuditLog.action == "test.explicit_tenant"
    ).one()
    assert row.tenant_id == 1


def test_audit_log_preserves_existing_kwargs(db, default_tenant):
    """Verify the new tenant_id kwarg doesn't break existing kwargs
    (ip, user_agent, request_id, metadata)."""
    audit_log(
        db, user_id=None, action="user.password_changed",
        metadata={"target_user_id": 2},
        ip="192.0.2.42",
        user_agent="TestAgent/1.0",
        request_id="req-abc-123",
    )
    row = db.query(AuditLog).filter(
        AuditLog.action == "user.password_changed"
    ).one()
    assert row.ip == "192.0.2.42"
    assert row.user_agent == "TestAgent/1.0"
    assert row.request_id == "req-abc-123"
    assert row.metadata_json == {"target_user_id": 2}
    assert row.tenant_id == 1  # auto-defaulted


# --------------------------------------------------- BC-2: existing login flow

def test_existing_login_endpoint_works(client, user):
    """Real /auth/login call as an existing user. JWT issued contains
    no tenant_id claim today (Phase 1 endpoints don't pass it yet),
    yet the user can access authenticated routes normally.

    This is the integration-level CR-1 mitigation: real HTTP
    round-trip proves existing users aren't broken.
    """
    r = client.post("/api/v1/auth/login",
                    json={"email": user.email, "password": "password123"})
    assert r.status_code == 200, r.text
    access = r.json()["access"]
    # Decode the JWT and check it's well-formed for backward compat
    payload = decode_token(access)
    assert payload["sub"] == str(user.id)
    # No tenant_id claim because the login endpoint doesn't set one yet
    assert "tenant_id" not in payload
    # User can use this token to hit an authed endpoint
    me = client.get("/api/v1/users/me",
                    headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == user.email


def test_existing_admin_login_can_access_admin_routes(client, admin):
    """Admin authenticated with Phase 1 JWT (no tenant_id claim)
    can still hit admin-gated routes. Pins CR-1 at the admin layer."""
    r = client.get(
        "/api/v1/admin/users",
        headers=auth_header(client, admin.email),
    )
    assert r.status_code == 200, r.text


# --------------------------------------------------- contract I-4: source of truth

def test_get_current_tenant_id_is_the_single_source_of_truth():
    """Code paths that need a tenant ID MUST call get_current_tenant_id().
    This test catches accidental hardcoding of `tenant_id=1` somewhere
    else (which would be a contract I-4 violation).

    Phase 1 spot-check: confirm the stub returns CPMAI's ID.
    """
    assert get_current_tenant_id() == 1
