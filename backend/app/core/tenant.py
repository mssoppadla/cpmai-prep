"""Tenant resolution — Phase 1 stubs, Phase 2 hooks.

Per contract I-4: ``get_current_tenant_id()`` is the SINGLE source of
truth for tenant identity. Every code path that needs a tenant ID
must call this function. No hardcoded ``tenant_id=1`` anywhere in the
application code outside the stubs in this module.

Phase 1: every call returns tenant 1 (CPMAI). Pure stub.
Phase 2: replace stub bodies with real resolution logic:
  - Primary: JWT ``tenant_id`` claim (per contract V1)
  - Secondary: subdomain lookup (acme.cpmaiexamprep.com → tenant slug)
  - Tertiary: custom-domain lookup (acme.com → tenant slug via DNS map)

The function signatures will NOT change in Phase 2. Only the
implementation bodies. That means all Phase 1 callers stay correct
when multi-tenancy goes live.

Backward compatibility (per BC-2): if a request's JWT has no
``tenant_id`` claim (old user signed in before Phase 1 deployed),
``get_current_tenant_id()`` returns 1 — matching the seeded CPMAI row.
Old users see no disruption.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.user import User


# The protected, permanent tenant. Application code (not just app/core)
# must treat this as an invariant — it must never be deleted.
CPMAI_TENANT_ID = 1


def get_current_tenant_id() -> int:
    """Return the tenant ID for the current request context.

    Phase 1 stub: always returns 1 (CPMAI).

    Phase 2 implementation (deferred): reads the ``tenant_id`` claim
    from the request's JWT, falling back to subdomain resolution if
    the JWT is absent (e.g. public reads of a tenant's Study Guide
    page). Falls back to 1 if neither yields a tenant.

    Callers SHOULD use this function rather than hardcoding 1 — that
    way the Phase 2 swap is a one-line change in this file.
    """
    # Phase 1: every request belongs to CPMAI.
    return CPMAI_TENANT_ID


def get_current_tenant(db: Session) -> "Tenant":
    """Load the Tenant row for the current request context.

    Phase 1 stub: always returns the CPMAI row (tenant id=1).

    Phase 2: derive tenant_id via get_current_tenant_id() and load
    the corresponding Tenant row, raising if not found (which should
    never happen — get_current_tenant_id() always returns a valid ID).
    """
    from app.models.tenant import Tenant  # local import to avoid cycles
    tenant_id = get_current_tenant_id()
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        # Should never hit this in Phase 1 — the migration seeds tenant 1.
        # If it happens, fail loudly rather than silently returning None.
        raise RuntimeError(
            f"Tenant id={tenant_id} not found. Migration 0023 may not "
            "have run. Run `alembic upgrade head`."
        )
    return tenant


def require_tenant_access(tenant_id: int, user: "User") -> None:
    """Enforce that ``user`` is allowed to operate on ``tenant_id``.

    Phase 1 stub: pass-through. All admin users see tenant 1; there's
    only one tenant.

    Phase 2 implementation: check that ``user.tenant_id == tenant_id``
    OR ``user`` has a super-admin role (and is operating within a
    SuperAdminScope — see contract D-3). Raise ``ForbiddenError`` if
    the user is trying to operate on a tenant they don't belong to.

    Returns: None on allowed; raises on denied.
    """
    # Phase 1: only one tenant exists. Every admin is implicitly
    # authorised to operate on it.
    return None


def is_cpmai_tenant(tenant_id: int) -> bool:
    """Convenience: True if the given tenant ID is the protected CPMAI row."""
    return tenant_id == CPMAI_TENANT_ID
