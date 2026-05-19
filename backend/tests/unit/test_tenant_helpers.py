"""Unit tests for app.core.tenant helpers.

Phase 1 contract (per docs/contracts/multi-tenancy-and-saas-integration.md):
- I-4: get_current_tenant_id() is the single source of truth
- H-1: tenant.py exists with stubs (Phase 1: always tenant 1)
- BC-2: backward compatibility for code that doesn't know about tenants

These tests pin the stub behaviour so Phase 2 implementations can swap
the bodies without breaking callers.
"""
from __future__ import annotations

import pytest

from app.core.tenant import (
    CPMAI_TENANT_ID,
    get_current_tenant,
    get_current_tenant_id,
    is_cpmai_tenant,
    require_tenant_access,
)
from app.models.tenant import Tenant
from app.models.user import User, UserRole


# ----------------------------------------------------- module constants

def test_cpmai_tenant_id_constant_is_one():
    """CPMAI is permanent tenant 1. Contract I-2."""
    assert CPMAI_TENANT_ID == 1


# ----------------------------------------------------- get_current_tenant_id

def test_get_current_tenant_id_returns_one_in_phase_1():
    """Phase 1 stub: always returns 1 (CPMAI). Contract I-4 + H-1.

    Phase 2 will replace the body to read from JWT.tenant_id claim.
    This test will need updating when Phase 2 lands, but the
    contract guarantees the function exists with this exact signature.
    """
    assert get_current_tenant_id() == 1


def test_get_current_tenant_id_no_args_required():
    """Function takes zero args. Phase 2 will read from request
    context implicitly (e.g. via contextvar set by middleware) —
    callers do not need to plumb the tenant ID through every function
    signature. Contract I-4."""
    # This will raise if the signature ever requires args.
    value = get_current_tenant_id()
    assert isinstance(value, int)


# ----------------------------------------------------- get_current_tenant

def test_get_current_tenant_returns_cpmai_row(db, default_tenant):
    """Phase 1 stub returns the CPMAI tenant row. Contract H-1."""
    tenant = get_current_tenant(db)
    assert tenant is not None
    assert tenant.id == 1
    assert tenant.slug == "cpmai"
    assert tenant.name == "CPMAI Prep"
    assert tenant.plan == "enterprise"
    assert tenant.status == "active"
    assert tenant.is_cpmai is True
    assert tenant.is_active is True


def test_get_current_tenant_raises_if_seed_missing(db):
    """If migration 0023 hasn't run / seeded tenant 1, fail loudly.

    Silent None return would propagate bad data downstream — better
    to crash and surface "your migration didn't run."
    """
    # Wipe the seeded tenant to simulate the broken state
    db.query(Tenant).filter_by(id=1).delete()
    db.commit()
    with pytest.raises(RuntimeError, match="Tenant id=1 not found"):
        get_current_tenant(db)


# ----------------------------------------------------- require_tenant_access

def test_require_tenant_access_passes_through_in_phase_1(db, default_tenant):
    """Phase 1 stub is a no-op. Every admin can operate on tenant 1
    because there's only one tenant. Contract H-1."""
    fake_user = User(
        id=1, email="admin@example.com", name="Admin",
        role=UserRole.ADMIN, password_hash="x",
    )
    # Should not raise
    result = require_tenant_access(tenant_id=1, user=fake_user)
    assert result is None


def test_require_tenant_access_returns_none_for_any_tenant_id_in_phase_1():
    """Phase 1 stub doesn't actually check anything. Even passing an
    arbitrary tenant_id doesn't raise, because the implementation is
    deferred to Phase 2. The test pins this behaviour so anyone editing
    the function knows they're flipping the Phase 2 switch."""
    fake_user = User(
        id=1, email="admin@example.com", name="Admin",
        role=UserRole.ADMIN, password_hash="x",
    )
    # In Phase 1 these are all no-ops. Phase 2 would raise for
    # tenant_id != fake_user.tenant_id.
    assert require_tenant_access(tenant_id=1, user=fake_user) is None
    assert require_tenant_access(tenant_id=42, user=fake_user) is None
    assert require_tenant_access(tenant_id=99999, user=fake_user) is None


# ----------------------------------------------------- is_cpmai_tenant

def test_is_cpmai_tenant_true_for_id_1():
    assert is_cpmai_tenant(1) is True


def test_is_cpmai_tenant_false_for_other_ids():
    assert is_cpmai_tenant(2) is False
    assert is_cpmai_tenant(0) is False
    assert is_cpmai_tenant(-1) is False
