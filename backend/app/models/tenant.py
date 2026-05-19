"""Tenant model — SaaS multi-tenancy primary entity.

Per contract I-2: CPMAI Prep is pre-seeded as tenant id=1 in migration
0023. This row is permanent — application code refuses to delete it.

Phase 1: only tenant_id=1 exists. All Phase 1 inserts use ``default=1``
either explicitly or implicitly via ``get_current_tenant_id()`` (see
``app/core/tenant.py``).

Phase 2: tenants table is the primary signup target. New tenants
register, pick a plan, configure their own payment gateway + branding,
and operate independently of CPMAI.

Plan + status are kept as free-form strings (not enums) so Phase 2 can
introduce new tiers without an enum migration. Acceptable values are
validated at the schema / API layer.
"""
from sqlalchemy import Column, Integer, String, Text, BigInteger, JSON, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)

    # Short URL-safe identifier. Phase 2 uses this in subdomain
    # ``{slug}.cpmaiexamprep.com`` or path ``/t/{slug}/`` (per contract
    # V1 — JWT primary, subdomain/path secondary).
    slug = Column(String(64), unique=True, nullable=False, index=True)

    # Display name shown to operators in super-admin UI.
    name = Column(String(128), nullable=False)

    # Plan tier. Phase 1 values: "enterprise" only (CPMAI).
    # Phase 2 values: "free" | "starter" | "growth" | "pro" | "enterprise".
    plan = Column(String(32), nullable=False, default="enterprise")

    # Operational status. "active" = normal use; "suspended" =
    # paywall returns 402 for end-users + admin UI shows a banner;
    # "deleted" = soft-deleted, retained for compliance/forensics.
    status = Column(String(32), nullable=False, default="active", index=True)

    # Per-tenant settings (per contract I-6 + H-7 namespacing).
    # JSON map of setting key → tenant-scoped value. Empty in Phase 1.
    # Phase 2: tenant overrides of globals + tenant-only keys (e.g. BYOK keys).
    settings_json = Column(JSON, nullable=False, default=dict)

    # Storage quota tracking (per contract S-2).
    # Phase 1: CPMAI = enterprise = unlimited (quota=NULL); usage
    # computed lazily via cron. Phase 2: real-time enforcement.
    storage_used_bytes = Column(BigInteger, nullable=False, default=0)
    storage_quota_bytes = Column(BigInteger)  # NULL = unlimited

    # Encrypted payment-gateway credentials for Flow B (tenant bills
    # their end-users). Phase 1: CPMAI's existing Razorpay/PayPal
    # creds live in the legacy ``payment_providers`` table (untouched).
    # Phase 2 tenants store theirs here, encrypted via Fernet
    # (ENCRYPTION_KEY). Never logged.
    payment_gateway_config_encrypted = Column(Text)

    # Feature flag overrides (per contract F-3). JSON map of
    # feature_name → enabled bool. Phase 1: empty. Phase 2: opt-in
    # tenants for beta features.
    feature_overrides = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(),
                        onupdate=func.now(),
                        nullable=False)

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} slug={self.slug!r} plan={self.plan!r}>"

    @property
    def is_cpmai(self) -> bool:
        """The protected tenant. App code must refuse to delete this."""
        return self.id == 1

    @property
    def is_active(self) -> bool:
        return self.status == "active"
