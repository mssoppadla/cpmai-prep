# Multi-tenancy & SaaS Integration Contract

**Status**: v1 — locked 2026-05-19
**Owners**: mssoppadla
**Related**: `docs/roadmap/phase-1-scope.md`, `docs/roadmap/phase-2-backlog.md`, `docs/roadmap/validation-gates.md`

## 0. Purpose

This document defines the invariants that all CPMAI Prep code must respect
so that Phase 2 (multi-tenant SaaS launch under TovaiTech) can be added
WITHOUT a major refactor and WITHOUT breaking existing CPMAI users.

Every PR that adds or modifies code in scope of this contract MUST:

- Confirm alignment in its description (see §17), OR
- Update this contract document in the same commit and explain the deviation
  (see §11)

Phase 1 (single tenant) and Phase 2 (multi-tenant) co-exist on the same
codebase. Tenant ID = 1 is reserved for CPMAI Prep. All future tenants
get IDs 2, 3, 4...

## 1. Scope

### In scope
- All new tables, models, services, endpoints, UI added in Phase 1
- Settings storage (`settings_store`)
- Audit logging
- Payment flows
- File/asset storage
- Authentication and authorisation
- Feature flags and plan-tier gating

### Out of scope (untouched in Phase 1)
- Existing `users`, `subscriptions`, `exam_sets`, `questions`,
  `assistant_logs`, `payments`, `plans` tables
- Existing `/api/v1/*` route signatures (additive only — no breaking changes)
- Existing JWT structure (additive `tenant_id` claim allowed)
- Existing admin UI shells (sidebar gets new items, but existing routes unchanged)

## 2. Core Invariants

### I-1. Every new table has a `tenant_id` column

```sql
tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE
```

- NOT NULL: prevents accidental insertions without a tenant
- DEFAULT 1: ensures Phase 1 code that doesn't pass tenant_id still works
- ON DELETE CASCADE: a deleted tenant cleanly removes their data
- Indexed: every new table has `INDEX (tenant_id, ...)` for hot query paths

### I-2. `tenants` table exists from Day 1

Created in migration 0023. Single row pre-seeded:

```sql
INSERT INTO tenants (id, slug, name, plan, status, created_at)
VALUES (1, 'cpmai', 'CPMAI Prep', 'enterprise', 'active', NOW());
```

This row is permanent and cannot be deleted. CPMAI is tenant zero.

### I-3. Every read query is tenant-scoped

Two acceptable patterns:

**Pattern A (preferred)**: SQLAlchemy event listener auto-injects
`tenant_id` filter into every query for tenant-scoped models. Models
opt-in via inheritance:

```python
class TenantScopedBase(Base):
    __abstract__ = True
    tenant_id = Column(Integer, ForeignKey("tenants.id"),
                        nullable=False, default=1)
```

**Pattern B (escape hatch)**: explicit filter in every query. Used for
cross-tenant admin operations (e.g., super-admin dashboard).

```python
db.query(ContentPage).filter(
    ContentPage.tenant_id == get_current_tenant_id()
).all()
```

PRs may use Pattern A by default; deviations to Pattern B must be
explicitly justified.

### I-4. `get_current_tenant_id()` is the single source of truth

Defined in `app/core/tenant.py`:

```python
def get_current_tenant_id() -> int:
    # Phase 1: always returns 1 (CPMAI)
    # Phase 2: resolves from JWT.tenant_id claim (primary),
    # falling back to subdomain/custom-domain lookup (secondary)
    return 1
```

ALL code paths that need a tenant ID call this function. No hardcoded
`tenant_id=1` inserts. No reading from JWTs directly. This single function
is the only place that changes in Phase 2.

**Decision V1** (locked 2026-05-19): JWT `tenant_id` claim is the primary
Phase 2 resolution strategy. Subdomain / custom domain are secondary
fallback for public unauthenticated requests.

### I-5. Audit logs are tenant-scoped

Every `audit_log()` call writes the current tenant_id. Existing
audit_logs rows (pre-migration) backfill to tenant_id=1.

**Decision Q1** (locked 2026-05-19): tenant_id column added to audit_logs
in migration 0023 with backfill = 1. Phase 2 does not need a follow-up
migration.

### I-6. Settings store has two-tier scoping

`settings_store.get(key)` resolves in this order:
1. Tenant-scoped value (`system_settings_tenant` table, key+tenant_id)
2. Global default value (`system_settings` table, current behaviour)

Phase 1: only global values exist. Tenant-scoped reads always fall
through to global. Phase 2: tenants can override globals.

Existing settings (e.g. `assistant.flow`, `auth.access_token_expire_minutes`)
keep working unchanged.

### I-7. Plan-tier feature gating

Every feature with plan-tier limits checks a single function:

```python
def can_use_feature(feature: str, tenant_id: int) -> bool:
    plan = get_tenant_plan(tenant_id)
    return feature in PLAN_FEATURES[plan]
```

Phase 1: CPMAI is on "enterprise" plan → all features enabled. No real
gating happens. The function exists as a stub so Phase 2 can plug in
real logic without touching feature code.

## 3. Backward Compatibility Guarantees

### BC-1. Existing API endpoints are unchanged

All `/api/v1/*` routes shipped before Phase 1 continue to:
- Accept the same request payloads
- Return the same response shapes
- Use the same auth (Bearer JWT, no `tenant_id` required in JWT yet)
- Honour the same rate limits

New endpoints MAY require `tenant_id` resolution but always default to 1
when absent.

### BC-2. Existing JWTs continue to work

Pre-Phase-1 JWTs (no `tenant_id` claim) are accepted. The auth layer
defaults their effective tenant_id to 1. This means: every CPMAI user
currently logged in stays logged in across Phase 1 deployment.

**Decision V3** (locked 2026-05-19): accept old JWTs with implicit
tenant_id = 1. Forcing re-login is hostile to existing users.

### BC-3. Existing data backfills cleanly

Migration 0023 adds `tenant_id` to existing tables only where absolutely
necessary (e.g. `audit_logs` for cross-tenant scoping later). Existing
rows backfill to `tenant_id=1` in the same migration.

No existing rows are renamed, moved, or deleted. No existing columns
change type.

### BC-4. Existing settings continue to work

The `settings_store` resolution adds a tenant lookup STEP, but if no
tenant-scoped value exists (which is the default state), behaviour is
identical to today.

### BC-5. Existing admin URLs are unchanged

`/admin/users`, `/admin/leads`, `/admin/settings`, etc. continue to
work. New admin pages are added at new URLs (`/admin/content-pages`,
`/admin/courses`, etc.).

### BC-6. Existing subscription flow is unchanged

`subscriptions` table, paywall checks, payment flows untouched. New
plans for TovaiTech tenants (Starter/Growth/Pro) are added but don't
affect CPMAI's existing free/premium plans.

## 4. Phase 1 Implementation Hooks (required by Phase 2)

Phase 1 PRs add these stubs/hooks even though they don't fully use them.
Phase 2 fills them in.

### H-1. `app/core/tenant.py` exists with stubs

```python
def get_current_tenant_id() -> int:
    return 1  # stub; Phase 2: resolve from JWT/subdomain

def get_current_tenant() -> Tenant:
    return db.get(Tenant, 1)  # stub

def require_tenant_access(tenant_id: int, user: User) -> None:
    # stub: in Phase 1, all admins see tenant 1
    pass
```

### H-2. `tenants` table seeded with CPMAI row

Migration 0023 creates the table and inserts CPMAI as tenant id=1.

### H-3. JWT structure supports tenant_id claim (additive)

`create_access_token()` adds optional `tenant_id` claim (defaults to 1
when absent). `decode_token()` exposes it. Phase 1 code can ignore it;
Phase 2 code uses it for tenant resolution.

### H-4. All new tables have tenant_id

Per I-1. Even if Phase 1 only writes tenant_id=1, the column exists.

### H-5. Asset storage paths are tenant-prefixed

R2/S3 object keys use the pattern:

```
tenants/{tenant_id}/recordings/{session_id}.mp4
tenants/{tenant_id}/content-images/{block_id}/{filename}
tenants/{tenant_id}/course-thumbnails/{course_id}.jpg
```

Phase 1: everything goes under `tenants/1/...`. Phase 2: each tenant's
data is naturally isolated by path.

### H-6. API endpoints reserve tenant-aware URL patterns

Phase 1 endpoints use simple paths:
`POST /api/v1/admin/content-pages`

These resolve tenant implicitly (always 1). Phase 2 keeps these working
unchanged but adds tenant-aware aliases where needed:
`POST /api/v1/admin/t/{tenant_slug}/content-pages` (Phase 2 only)

Implicit-tenant routes resolve via JWT.tenant_id (or default 1).

### H-7. Settings keys are namespaced for future tenant override

New settings use tenant-friendly prefixes:
- `content.ai.style_guide` (settable globally; tenant-overridable in Phase 2)
- `lms.video.default_player` (same)
- `automation.openai.byo_key` (tenant-scoped in Phase 2; absent in Phase 1)

## 5. Data Isolation Contract

### D-1. No tenant can read another tenant's data

Phase 1: only tenant 1 exists, so vacuously true.

Phase 2: every API handler asserts `resource.tenant_id == current_tenant_id`
OR returns 404 (not 403, to avoid information disclosure about which
tenants exist).

### D-2. Tenant deletion cascades cleanly

If tenant N is deleted: all rows with `tenant_id = N` cascade-delete,
all R2 objects under `tenants/N/...` are purged, all audit_logs rows
where tenant_id=N are anonymised (kept for compliance).

### D-3. Cross-tenant queries are explicit and audit-logged

Super-admin operations that span tenants (e.g. "total revenue across all
tenants") use a dedicated `SuperAdminScope` context manager:

```python
with SuperAdminScope(user):
    # tenant filter bypassed within this block
    # every query in this block writes an audit_logs row
    total = db.query(...).all()
```

## 6. Payment Isolation Contract

### P-1. Two payment flows

- **Flow A**: TovaiTech bills tenant (monthly SaaS subscription).
  Uses TovaiTech's own Razorpay/Stripe account.
- **Flow B**: Tenant bills their end-users. Uses tenant's OWN gateway
  credentials, stored encrypted in `tenants.payment_gateway_config`.

CPMAI Prep currently uses Flow B for its own subscription sales (CPMAI
is the tenant; its students are the end-users). Phase 2 simply adds Flow A
on top — no change to Flow B.

### P-2. Tenant gateway credentials are encrypted at rest

Stored using Fernet encryption (existing `ENCRYPTION_KEY` infra).
Decrypted only at payment-call time. Never logged.

### P-3. Phase 1: CPMAI's existing Razorpay/PayPal credentials migrate to tenant 1

The existing `payment_providers` configuration becomes tenant 1's
configuration. No data is moved or renamed.

## 7. Storage Isolation Contract

### S-1. Per-tenant prefix on every asset

Per H-5. No exceptions. Even shared assets (e.g. AI-generated thumbnails)
get prefixed by the tenant that owns the originating content.

### S-2. Per-tenant storage quota tracking

Each tenant has `tenants.storage_used_bytes` and `tenants.storage_quota_bytes`.
Phase 1: CPMAI is enterprise → unlimited. Phase 2: paid tiers enforce.

Storage usage is computed lazily (cron job) for Phase 1; real-time in
Phase 2.

### S-3. Signed URLs for all user-served assets

R2 objects are NEVER public. Every user-facing URL is signed, 1-hour TTL,
single-use where possible. Tied to user's session + subscription check.

## 8. Feature Flag Contract

### F-1. Feature flags are per-tenant

The function `is_feature_enabled(feature: str, tenant_id: int)` is the
single check. Phase 1: returns True for tenant 1 for all features
shipped to CPMAI.

### F-2. Plan-tier features are gated server-side

UI may hide unavailable features, but server enforces. Bypassing the UI
returns 403 with `code: "feature_not_available_in_plan"`.

### F-3. Beta features are opt-in per tenant

If a feature is launched as beta, tenants are added via
`tenants.feature_overrides JSONB` until promoted to GA.

## 9. Migration Contract

### M-1. All Phase 1 migrations are additive only

No DROP COLUMN, no ALTER COLUMN that changes existing semantics.
Existing data is never modified except by explicit, documented backfills.

### M-2. Downgrades are forward-only

Per the existing data-preservation policy. `downgrade()` raises
`NotImplementedError`. Reversals happen via UI actions (e.g. revoke a
manual grant), not schema rollbacks.

### M-3. Tenant_id backfills happen in a single migration

Migration 0023 adds `tenant_id` to all existing tables that need it and
backfills `1` in the same transaction. No multi-step migrations that
leave the system in an inconsistent state.

## 10. Audit & Observability Contract

### A-1. Every cross-tenant operation logs to audit_logs

With action prefix `super_admin.*` and `tenant_id` of the originator +
`target_tenant_id` in metadata.

### A-2. Every tenant-scoped mutation logs to audit_logs

With `tenant_id` set to the operating tenant. Phase 1: always tenant 1.

### A-3. Tenant admins can see only their own audit logs

Filtered by `tenant_id = current_tenant_id`. Super-admins see all
(within a `SuperAdminScope`).

## 11. Process for Updating This Contract

A PR that needs to deviate from any rule above must:

1. Update this file in the same commit with:
   - The new rule (or amended rule)
   - The rationale (why the original wasn't workable)
   - The migration plan (how existing code aligns to the new rule)

2. Tag the PR with `contract-update` label.

3. Require a review acknowledgement that the deviation is acceptable.

The contract is a living document. Disagreement is expected. Silent
deviation is not.

## 12. Validation Checklist (run before every Phase 1 PR merges)

- [ ] Every new table has `tenant_id` (per I-1)
- [ ] No hardcoded `tenant_id=1` in business logic (use `get_current_tenant_id()`)
- [ ] No new endpoints break existing route signatures (per BC-1)
- [ ] No new fields in existing tables that would require backfill (per M-1)
- [ ] No new global state that can't be tenant-scoped later (per I-6, I-7)
- [ ] Asset paths use the `tenants/{id}/...` prefix (per S-1)
- [ ] New audit_log calls include current tenant_id (per A-2)
- [ ] Settings keys use namespaced format (per H-7)
- [ ] Migration follows additive-only policy (per M-1)

## 13. Changelog

### v1 — 2026-05-19 — Initial draft

Initial contract. Locks invariants I-1 through I-7, backward compatibility
BC-1 through BC-6, Phase 1 implementation hooks H-1 through H-7, data
isolation D-1..D-3, payment isolation P-1..P-3, storage isolation S-1..S-3,
feature flags F-1..F-3, migration policy M-1..M-3, observability A-1..A-3.

**Decisions locked**:
- V1: JWT primary tenant resolution, subdomain secondary
- V2: tenant_id default = 1 in Phase 1
- V3: Old JWTs accepted with implicit tenant_id = 1
- Q1: audit_logs gets tenant_id column in migration 0023, backfill = 1
- Q2: content blocks stored as single JSONB column on `content_pages.blocks`
- Q3: per-page `nav_visibility` enum (always / authenticated / subscribed / hidden)

(Future entries appended here as the contract evolves.)

## 14. Impact Inventory by existing module

Concrete audit of what changes in cpmai-prep when Phase 1 lands.

### 14.1 Backend core (`app/core/*`)

| File | Current behaviour | Phase 1 change | Severity | Backward compat? |
|---|---|---|---|---|
| `config.py` | Loads env vars | Adds new env vars: `R2_*`, `ZOOM_*`, `OPUSCLIP_*`, `BUFFER_*`, `ELEVENLABS_*` | Low (additive) | ✅ |
| `database.py` | `SessionLocal`, Base | Unchanged | None | ✅ |
| `security.py` | JWT mint/decode, password hashing, admin-tunable token lifetimes | Adds optional `tenant_id` claim. Existing JWTs decode fine; missing claim defaults to 1 | Low | ✅ |
| `deps.py` | `get_current_user`, `get_admin_user`, `get_super_admin_user` | Adds `get_current_tenant()` and `get_current_tenant_id()` helpers | Low | ✅ |
| `settings_store.py` | Global key-value with Redis cache + pubsub | Adds optional `tenant_id=` param. If absent, falls back to global lookup | Medium | ✅ |
| `audit.py` | `audit_log(db, user_id, action, metadata)` | Adds optional `tenant_id=` kwarg. Defaults to `get_current_tenant_id()` | Low | ✅ |
| `exceptions.py` | App errors with codes | Adds new error codes: `tenant_not_found`, `feature_not_in_plan`, `storage_quota_exceeded` | None | ✅ |
| `limiter.py` | Slowapi rate limiter | Unchanged | None | ✅ |
| `redis.py` | Redis client | Unchanged | None | ✅ |
| **NEW** `tenant.py` | (doesn't exist) | Creates `get_current_tenant_id()`, `Tenant` lookup, plan-gating helpers | New | N/A |

### 14.2 Auth & user management

| Component | Phase 1 change | Severity |
|---|---|---|
| `/auth/login`, `/auth/signup`, `/auth/refresh` | Route signatures unchanged. JWT may include optional `tenant_id` claim | None |
| `/auth/google` | Unchanged | None |
| Existing `users` table | Untouched in Phase 1. Phase 2: add `tenant_id` with default=1 | Low |
| Existing JWTs in browsers | Continue working — missing claim → tenant_id=1 | None |
| `Subscription` paywall | Unchanged for exam access. New helpers for course/session access (separate functions) | Low |

### 14.3 Existing API endpoints — full backward compat

| Endpoint group | Phase 1 change | Severity |
|---|---|---|
| `/api/v1/auth/*` | Optional `tenant_id` claim in JWT | None |
| `/api/v1/users/me*` | No change. GDPR export adds course/session data (additive) | Low |
| `/api/v1/assistant/chat` | No change. RAG corpus unchanged | None |
| `/api/v1/exam-sets/*` | No change | None |
| `/api/v1/pricing/*` | No change | None |
| `/api/v1/payments/*` | No change | None |
| `/api/v1/leads` | No change | None |
| `/api/v1/admin/users` | No change. New admin endpoints added separately | Low |
| `/api/v1/admin/settings` | No change | None |
| `/api/v1/admin/llm-providers` | No change | None |
| `/api/v1/admin/subscriptions/*` | No change (already shipped in feat/session-router-admin-grant) | None |

### 14.4 Existing models — full backward compat

| Model | Phase 1 change | Severity |
|---|---|---|
| `User` | No change | None |
| `Subscription` | No change. New gating logic uses these rows but doesn't modify schema | None |
| `Plan`, `OfferCode`, `Payment` | No change | None |
| `Question`, `ExamSet`, `ExamSession`, `ExamAttemptAnswer` | No change | None |
| `AssistantLog`, `AssistantFlaggedTurn` | No change | None |
| `Lead`, `LeadSource` | No change | None |
| `AuditLog` | **Optional change**: add nullable `tenant_id` column. Existing rows backfill = 1 (per Q1) | Medium |
| `JourneyEvent` | Same as `AuditLog` | Medium |
| `SystemSetting` | No change | None |
| `RagChunk` | Already has `tenant_id` column. Phase 1: ensure new RAG sources tag tenant 1 | Low |
| `LLMProviderConfig`, `PaymentProviderConfig` | No change. Phase 2 makes per-tenant | None |

### 14.5 Existing services

| Service | Phase 1 change | Severity |
|---|---|---|
| `services/assistant/*` | No change. RAG corpus indexing extended for new Study Guide content | Low |
| `services/assistant/rag/*` | New `source_type='content_page'` added to retrieval | Low |
| `services/auth/google_auth/*` | No change | None |
| `services/geoip/*` | No change | None |
| `services/payment_lifecycle.py` | No change | None |
| `services/exam_service.py` | No change. New helpers `services/lms/*` added separately | Low |
| `services/pricing_service.py` | No change | None |
| `services/lead_scoring.py` | No change | None |
| **NEW** `services/content/*` | Block validation + AI generation | New |
| **NEW** `services/lms/*` | Course/chapter/lesson logic | New |
| **NEW** `services/zoom/*` | Zoom API + webhook handling | New |
| **NEW** `services/automation/*` | APScheduler + campaign runners | New |
| **NEW** `services/storage/*` | R2 upload/signed-URL service | New |

### 14.6 Frontend components

| Component | Phase 1 change | Severity |
|---|---|---|
| `components/layout/SiteHeader` | Add 1–3 new nav links via `/cms/v1/nav` (configurable visibility per Q3) | Low |
| `components/layout/SiteFooter` | No change | None |
| `components/assistant/AssistantWidget` | No change | None |
| `components/exam/*` | No change | None |
| `components/lead/*` | No change | None |
| `components/admin/UserSubscriptionsPanel` | No change | None |
| **NEW** `components/cms/BlockEditor` | BlockNote editor wrapper | New |
| **NEW** `components/lms/CoursePlayer`, `LessonProgressBar` | Video player + progress | New |
| **NEW** `components/sessions/ZoomEmbed`, `RecordingPlayer` | Zoom SDK embed + R2 playback | New |
| **NEW** `components/automation/CampaignBuilder` | Workflow config UI | New |

### 14.7 Frontend routes

| Route | Phase 1 change | Severity |
|---|---|---|
| `/` (landing) | No change | None |
| `/login`, `/signup` | No change | None |
| `/dashboard` | Optional: add "My Courses" + "Upcoming Sessions" widgets | Low |
| `/exams/[slug]` | No change | None |
| `/pricing` | No change | None |
| `/admin/*` (existing) | New pages added at new URLs; existing pages unchanged | Low |
| **NEW** `/study-guide`, `/study-guide/[slug]` | Public CMS routes | New |
| **NEW** `/courses`, `/courses/[slug]`, `/courses/[slug]/lessons/[lid]` | User LMS routes | New |
| **NEW** `/sessions`, `/sessions/[id]/live`, `/sessions/[id]/recording` | User session routes | New |

### 14.8 Database schema

| Change | Migration | Severity | Mitigation |
|---|---|---|---|
| New `tenants` table (singleton row for CPMAI) | 0023 | Low | Pre-seeded with id=1; can never be deleted |
| Add nullable `tenant_id` to `audit_logs` | 0023 | Medium | Nullable; existing rows backfilled = 1 in same migration |
| New `content_pages` with single JSONB `blocks` column (per Q2) | 0024 | None | Additive |
| New `content_pages.nav_visibility` enum (per Q3): always / authenticated / subscribed / hidden | 0024 | None | Additive |
| New `courses`, `chapters`, `lessons` | 0025 | None | Additive |
| New `enrollments`, `lesson_progress` | 0025 | None | Additive |
| New `zoom_sessions`, `recordings` | 0026 | None | Additive |
| New `campaigns`, `campaign_runs` | 0027 | None | Additive |

### 14.9 Configuration & deployment

| Item | Phase 1 change | Severity |
|---|---|---|
| `backend/.env` | Add: `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET`, `R2_PUBLIC_URL`, `ZOOM_API_KEY`, `ZOOM_API_SECRET`, `ZOOM_SDK_KEY`, `ZOOM_SDK_SECRET`, `ZOOM_WEBHOOK_SECRET`, `OPUSCLIP_API_KEY`, `BUFFER_ACCESS_TOKEN`, `ELEVENLABS_API_KEY` | Low |
| `docker-compose.yml` | No change required | None |
| `Caddyfile` | Optional: add subdomain rules for Phase 2 readiness (no-op in Phase 1) | None |
| `scripts/preflight.sh` | New tests added; existing tests continue to pass | Low |
| GitHub Actions deploy | No change | None |
| VPS RAM/CPU | APScheduler runs in same process; ~50MB extra RAM at idle | Low |
| VPS storage | Asset uploads go to R2, not VPS disk | None |

### 14.10 Operational concerns

| Concern | Phase 1 change | Severity | Mitigation |
|---|---|---|---|
| Background jobs | APScheduler runs in FastAPI process | Medium | If scheduler crashes, FastAPI requests continue. Health endpoint + restart-on-failure |
| Long-running operations | Pictory/R2 uploads take minutes | Medium | Webhook-driven completion; no request-thread blocking |
| External API failures | Zoom/Pictory/Buffer can be down | Medium | Idempotent retries; graceful degradation; admin sees clear error state |
| Storage costs | R2 bills by storage | Low | Free tier 10GB; ₹1.25/GB beyond. At 100GB: ₹125/mo |
| Webhook security | Zoom + Pictory + Buffer all send webhooks | High | HMAC signature verification on every handler; replay protection via idempotency keys |
| Storage quota | Tenants could upload unlimited | Medium (Phase 2) | Phase 1: trust CPMAI. Phase 2: enforce quota per tenant |

## 15. Risk Register and Mitigation Strategies

Every PR touching a risky surface references the relevant risk ID in its description.

### 15.1 Critical risks (CR) — production-breaking if mishandled

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **CR-1** | Existing user logins break after Phase 1 deploy | Low | Critical | JWT `tenant_id` claim is OPTIONAL. Decode path always works. Auth layer defaults missing claim to 1. Test: `test_old_jwt_without_tenant_claim_still_works` |
| **CR-2** | Tenant_id scoping silently filters out CPMAI data | Low | Critical | Phase 1 tenant_id default = 1 on every INSERT. Test: `test_existing_data_visible_after_migration_0023` |
| **CR-3** | New tables block app startup due to missing migration | Low | Critical | Deploy pipeline runs `alembic upgrade head` before app starts. Smoke test verifies schema |
| **CR-4** | APScheduler crashes silently → marketing campaigns stop | Medium | High | Scheduler health endpoint `/internal/scheduler/status`. Alert if no successful job in N minutes. Heartbeat job every 60 seconds |
| **CR-5** | Zoom recording webhook missed → student can't access | Medium | High | Idempotent webhook handler with deduplication. Nightly reconciliation job queries Zoom API for missing recordings |
| **CR-6** | R2 storage credentials leak → tenant data exposed | Low | Critical | Credentials only in `.env`. Signed URLs short-TTL (1 hour). Per-tenant prefix limits blast radius |

### 15.2 High risks (HR)

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **HR-1** | Subscription paywall doesn't gate new course access correctly | Medium | High | Test matrix: subscribed/unsubscribed × course/session/recording. ~20 test cases |
| **HR-2** | settings_store changes break existing reads | Low | High | `get(key, tenant_id=None)` keeps old signature. All ~30 existing callers tested |
| **HR-3** | `audit_log()` signature change breaks existing callers | Low | High | `tenant_id` is keyword-only optional. All ~50 existing callers tested |
| **HR-4** | RAG indexing pollutes corpus with new Study Guide content for legacy chat | Low | High | New `source_type='content_page'` added. Legacy handlers explicitly exclude it |
| **HR-5** | BlockNote editor JS bundle blows up admin page size | Medium | Medium | Code-split: load only on /admin/content-pages. Initial admin bundle <500KB |
| **HR-6** | Zoom Meeting SDK has hard meeting-ID ban list | Low | High | Server-signed JWTs. Test against Zoom API limits (100 meetings/day Pro) |
| **HR-7** | LinkedIn auto-post causes account ban for CPMAI | Medium | High | Use ONLY Buffer's official LinkedIn integration. Never call LinkedIn API directly |
| **HR-8** | OpenAI cost explosion from runaway campaign | Low | High | Per-tenant `ai_quota_tokens_remaining` enforced at API layer. Slack alert at 80% quota |

### 15.3 Medium risks (MR)

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **MR-1** | New admin pages break sidebar on small screens | Medium | Low | Use existing admin layout component. Test responsive breakpoints |
| **MR-2** | Course Player video doesn't work on iOS Safari | Medium | Medium | Use Plyr (handles iOS HLS quirks). Test on real iOS device before launch |
| **MR-3** | BlockNote saves don't sync if user has spotty network | Medium | Medium | Optimistic UI with auto-retry. Visible save state. Last-write-wins |
| **MR-4** | Tenant_id NULL on existing audit_logs confuses Phase 2 queries | Low | Medium | Single backfill in migration 0023. NOT NULL constraint in Phase 2 |
| **MR-5** | Pictory API rate limits hit during peak | Low | Medium | Queue + retry with exponential backoff. Per-tenant quota |
| **MR-6** | Buffer access token expires (30-day rotation) | Medium | Medium | Token refresh job daily. Admin email if refresh fails |
| **MR-7** | Existing tests fail due to new fixtures | High | Low | Add `default_tenant` fixture to `conftest.py`. Existing tests don't need it (default=1 auto-applies) |

### 15.4 Low risks (LR)

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **LR-1** | New env vars missing in dev → features broken | Medium | Low | Fail-fast at app boot with clear error: "ZOOM_API_KEY not set; live sessions disabled" |
| **LR-2** | Migration 0023 takes too long on large audit_logs table | Low | Low | Backfill in chunks if >1M rows. Indexed `WHERE tenant_id IS NULL` makes UPDATE fast |
| **LR-3** | JSONL log size grows from new feature events | High | Low | Log rotation already in place. New events use existing format |
| **LR-4** | Frontend `lib/api.ts` becomes too large | High | Low | Split into separate files: `lib/api/cms.ts`, `lib/api/lms.ts`. Re-export from `lib/api.ts` |

## 16. Files-Touched Matrix (per Phase 1 feature)

For each Phase 1 feature, which existing files get touched.

### Feature 1: CMS (Study Guide pages)

| Existing file | Type of change |
|---|---|
| `app/api/v1/router.py` | Register new `/cms/v1/*` and `/admin/content-pages/*` routers |
| `app/api/v1/endpoints/admin/router.py` | Add new admin sub-router |
| `app/core/tenant.py` | NEW |
| `app/services/assistant/rag/handler_support.py` | Add `content_page` to source_types (optional) |
| `frontend/src/components/layout/SiteHeader.tsx` | Add "Study Guide" nav link |
| `frontend/src/app/admin/layout.tsx` | Add "Content Pages" sidebar item |
| `frontend/src/lib/api.ts` | Add `admin.contentPages.*` and `cms.pages.*` namespaces |
| `frontend/src/types/api.ts` | Add ContentPage, ContentBlock types |

Net: **8 files**, all additive.

### Feature 2: LMS (Courses + Chapters + Lessons)

| Existing file | Type of change |
|---|---|
| `app/api/v1/router.py` | Register new `/courses/*` and `/admin/courses/*` routers |
| `app/api/v1/endpoints/admin/router.py` | Add new admin sub-router |
| `app/services/exam_service.py` | **No change**. New `services/lms/access.py` added separately |
| `frontend/src/components/layout/SiteHeader.tsx` | Add "Courses" nav link |
| `frontend/src/app/admin/layout.tsx` | Add "Courses" sidebar item |
| `frontend/src/app/dashboard/page.tsx` | Optional: add "My Courses" widget |
| `frontend/src/lib/api.ts` | Add `admin.courses.*` and `courses.*` namespaces |
| `frontend/src/types/api.ts` | Add Course, Chapter, Lesson, Enrollment, Progress types |

Net: **8 files**, all additive.

### Feature 3: Zoom (Live sessions + recordings)

| Existing file | Type of change |
|---|---|
| `app/api/v1/router.py` | Register `/sessions/*`, `/admin/sessions/*`, `/webhooks/zoom` |
| `app/api/v1/endpoints/admin/router.py` | Add new admin sub-router |
| `app/core/config.py` | Add Zoom env vars |
| `frontend/src/components/layout/SiteHeader.tsx` | Add "Live Sessions" nav link (subscribed users) |
| `frontend/src/app/admin/layout.tsx` | Add "Sessions" sidebar item |
| `frontend/src/lib/api.ts` | Add `admin.sessions.*` and `sessions.*` namespaces |

Net: **6 files**, all additive.

### Feature 4: Social automation (campaigns)

| Existing file | Type of change |
|---|---|
| `app/main.py` | Add APScheduler startup hook |
| `app/api/v1/router.py` | Register `/admin/campaigns/*` and `/webhooks/{pictory,buffer}` |
| `app/api/v1/endpoints/admin/router.py` | Add new admin sub-router |
| `app/core/config.py` | Add OpusClip, Buffer, ElevenLabs env vars |
| `frontend/src/app/admin/layout.tsx` | Add "Campaigns" sidebar item |
| `frontend/src/lib/api.ts` | Add `admin.campaigns.*` namespace |

Net: **6 files**. One non-trivial: `app/main.py` (APScheduler boot).

### Multi-tenancy hooks (contract H-1..H-7)

| Existing file | Type of change |
|---|---|
| `app/core/security.py` | Add optional `tenant_id` param to `create_access_token()` |
| `app/core/audit.py` | Add optional `tenant_id` kwarg to `audit_log()` |
| `app/core/settings_store.py` | Add optional `tenant_id` param to `get/set()` |
| `app/core/deps.py` | No change; new `tenant.py` imported as needed |
| `tests/conftest.py` | Add `default_tenant` fixture (uses or creates tenant id=1) |

Net: **5 files**, all additive (no signature breaks).

**Total: ~30 existing files touched across Phase 1. All changes additive. Zero existing tests should break.**

## 17. Pre-PR Checklist (for every Phase 1 PR)

```markdown
### Contract alignment
- [ ] Adheres to invariants I-1..I-7
- [ ] If deviating, contract updated in this commit

### Backward compatibility
- [ ] No existing endpoint route changed
- [ ] No existing function signature changed (additive only)
- [ ] No existing JWT-decoding logic altered
- [ ] No existing query changed to include tenant_id filter
- [ ] No existing migration revised (additive only)

### Risk register
- [ ] Critical risks (CR-1..CR-6) reviewed; mitigations applied if relevant
- [ ] High risks (HR-1..HR-8) reviewed
- [ ] New risks added to contract if discovered

### Tests
- [ ] Existing test suite passes (all ~380 backend + 30 frontend)
- [ ] New tests cover: success path, backward compat, tenant scope correctness
- [ ] Risk-specific tests added

### Local testing (§18)
- [ ] §18.1 universal gates passed
- [ ] §18.2-18.6 gates passed where applicable
- [ ] Manual scenarios documented in PR description
```

## 18. Mandatory Local Testing Gate

NO code is pushed to GitHub (any branch — feature, main, hotfix) without
completing the local testing checklist below for the specific feature
being shipped. This is non-negotiable and overrides any time pressure.

### 18.1 Universal gates (every PR)

- [ ] `./scripts/preflight.sh` runs locally and passes
      (vitest + backend pytest, all ~380+ tests green)
- [ ] All NEW tests added for this PR pass
- [ ] No existing test was deleted, skipped, or weakened to make CI green
- [ ] Docker stack (postgres + redis) is up and DB migration applied
- [ ] Frontend dev server (`npm run dev`) builds without errors

### 18.2 UI-touching PRs (additional gates)

If the PR changes any frontend route or component:

- [ ] Manually loaded the changed page in a real browser (not just tests)
- [ ] Verified the change works for an existing CPMAI user account
      (no re-login required; existing JWT still valid)
- [ ] Verified the change works for a brand-new user signing up
- [ ] Verified the change works on mobile viewport (DevTools responsive mode)
- [ ] Verified the change does NOT break adjacent existing pages
      (e.g. changing /admin layout — check /admin/users still renders)
- [ ] Console has no new errors or warnings introduced by this PR

### 18.3 External API integration PRs (additional gates)

If the PR adds calls to Zoom, OpenAI, R2, Pictory, Buffer, ElevenLabs,
or any new third-party service:

- [ ] Real API credentials configured in local `.env`
- [ ] Happy path tested end-to-end with real API
      (not just mocked unit tests)
- [ ] Error path tested by intentionally breaking credentials
      and verifying graceful failure
- [ ] Webhook receivers (if any) tested with a real webhook from the
      provider's test/sandbox panel
- [ ] Rate limit / quota behaviour verified
      (e.g. trigger a 429 and confirm we retry correctly)
- [ ] Cost of the integration test run documented in PR description
      (e.g. "this test cost ₹3 of OpenAI credits")

### 18.4 Database migration PRs (additional gates)

If the PR includes an Alembic migration:

- [ ] `alembic upgrade head` runs cleanly on a fresh empty DB
- [ ] `alembic upgrade head` runs cleanly on a dev DB with seed data
      (verifies backfill works on existing rows)
- [ ] Smoke test against the migrated DB: existing endpoints still work
- [ ] If the migration backfills existing rows, count of affected rows
      documented in PR description
- [ ] `downgrade()` raises NotImplementedError (per M-2)

### 18.5 Auth/security-touching PRs (additional gates)

If the PR changes `security.py`, `deps.py`, `tenant.py`, or any
JWT/auth/RBAC logic:

- [ ] Existing user's stored JWT still decodes correctly
- [ ] New JWT issued post-change has expected shape (manually decoded)
- [ ] Admin user can still access admin routes
- [ ] Regular user CANNOT access admin routes (verified with real
      browser session, not just test)
- [ ] Tenant-scoping does NOT filter out CPMAI's existing data
      (manually queried the DB to confirm data is visible)

### 18.6 Feature-specific manual scenarios (per PR)

The PR description must list 3–5 concrete manual scenarios that were
clicked through end-to-end locally. Example for the CMS PR:

> Manual scenarios tested locally:
> 1. Created a new page in /admin/content-pages → added 5 blocks of
>    various types → published → loaded /study-guide → confirmed page
>    renders correctly
> 2. Edited an existing block → saved → reloaded → change persisted
> 3. Dragged a block to reorder → saved → order preserved
> 4. Set nav_visibility=authenticated → logged out → confirmed link
>    disappeared from header → logged in → confirmed it reappeared
> 5. Loaded the page as an existing CPMAI user → confirmed their
>    existing session still works on /dashboard

### 18.7 What "tested locally" does NOT mean

- "I ran the tests in CI on a draft PR" — not local
- "It compiled" — not tested
- "I'm fixing a typo so I'm skipping" — typos in copy still need a
  visual check; typos in code need preflight
- "It's just docs" — fine to skip 18.2–18.6, but 18.1 still applies if
  there's any code

### 18.8 Reviewer responsibility

The PR reviewer (mssoppadla) confirms by reading the "Local Testing"
section of the PR description that the gates were honoured. PRs missing
this section are blocked from merge regardless of how clean the code looks.

### 18.9 Emergency override

A production-down incident may justify shipping without full 18.2–18.6
testing IF AND ONLY IF:
- The change is <10 LOC
- The change is reverting a recent commit, OR adding a single
  config/env value
- The PR description explicitly says "EMERGENCY OVERRIDE: skipped
  manual gates because [specific reason]"
- A follow-up PR within 24h restores full testing for the fix
