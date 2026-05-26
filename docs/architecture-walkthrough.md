# CPMAI Prep — End-to-End Architecture Walkthrough

**Audience:** Head of Engineering review.
**Purpose:** Single document that walks the whole system from request to disk, calls out every conscious engineering decision, and shows where the iterative-but-scalable path lives.

Reading order: §1–§3 give the shape. §4–§13 are the subsystems. §14–§19 cover the engineering standards (CI/CD, observability, quality gates, rollback). §20–§21 are scalability and discipline.

Last updated: 2026-05-25.

---

## 1. Product context in one paragraph

CPMAI Prep is a multi-tenant SaaS for exam preparation: paid courses (LMS), live cohorts (Zoom), a Retrieval-Augmented chat assistant (the original product), payments in INR + USD, and an admin CMS that lets ops change copy, prices, classifier keywords, LLM providers, social-automation cadences, and Zoom credentials **without a redeploy.** The platform runs on a single Hostinger VPS today and is intentionally architected so the path to multi-node / R2 / multi-region is a swap-not-a-rewrite.

---

## 2. System topology (one picture)

```mermaid
graph TB
    subgraph CLIENT["Clients"]
        WEB["Next.js 14 SPA<br/>App Router · TS · Tailwind"]
        WIDGET["AssistantWidget<br/>(injected on every page)"]
        ZOOM_SDK["Zoom Meeting SDK<br/>(browser embed)"]
    end

    subgraph EDGE["Hostinger VPS — Edge"]
        CADDY["Caddy<br/>TLS · HTTP/2 · gzip<br/>auto-LetsEncrypt"]
    end

    subgraph APP["Application tier (Docker Compose)"]
        FE["frontend container<br/>next start :3000"]
        BE["backend container<br/>FastAPI + uvicorn :8001<br/>+ APScheduler in lifespan"]
        STATIC["StaticFiles mount<br/>/uploads/* → named volume"]
    end

    subgraph DATA["Data tier"]
        PG[("PostgreSQL 16<br/>+ pgvector")]
        REDIS[("Redis 7<br/>cache · pubsub · rate-limit")]
        UPLOADS[("cpmai-uploads<br/>named docker volume")]
        BACKUPS[("/var/backups/cpmai-prep<br/>DB dumps + uploads tarballs")]
    end

    subgraph EXT["External"]
        OPENAI["OpenAI<br/>(generation + embeddings)"]
        ANTHROPIC["Anthropic<br/>(fallback / future routing)"]
        ZOOM_API["Zoom REST + Webhooks"]
        RAZOR["Razorpay (INR)"]
        PAYPAL["PayPal (USD/EUR)"]
        GOOGLE["Google OAuth"]
        MAXMIND["MaxMind GeoIP"]
        SOCIAL["LinkedIn / X / Meta APIs<br/>(via per-tenant tokens)"]
    end

    subgraph CI["GitHub Actions"]
        WF1["backend-ci.yml"]
        WF2["frontend-ci.yml"]
        WF3["security-scan.yml"]
        WF4["deploy.yml<br/>(prod gate)"]
    end

    WEB --> CADDY
    WIDGET --> CADDY
    ZOOM_SDK -.signed JWT.-> ZOOM_API
    CADDY --> FE
    CADDY --> BE
    CADDY --> STATIC
    BE --> PG
    BE --> REDIS
    BE --> UPLOADS
    STATIC --> UPLOADS
    BE --> OPENAI
    BE --> ANTHROPIC
    BE --> ZOOM_API
    ZOOM_API -.webhook.-> BE
    BE --> RAZOR
    BE --> PAYPAL
    RAZOR -.webhook.-> BE
    PAYPAL -.webhook.-> BE
    BE --> GOOGLE
    BE --> MAXMIND
    BE --> SOCIAL
    PG -.nightly dump.-> BACKUPS
    UPLOADS -.nightly tar.-> BACKUPS
    CI --> APP

    classDef client fill:#1d4ed8,stroke:#1e40af,color:#fff
    classDef edge fill:#a16207,stroke:#713f12,color:#fff
    classDef app fill:#475569,stroke:#334155,color:#fff
    classDef data fill:#0f766e,stroke:#134e4a,color:#fff
    classDef ext fill:#7c3aed,stroke:#5b21b6,color:#fff
    classDef ci fill:#be185d,stroke:#9d174d,color:#fff

    class WEB,WIDGET,ZOOM_SDK client
    class CADDY edge
    class FE,BE,STATIC app
    class PG,REDIS,UPLOADS,BACKUPS data
    class OPENAI,ANTHROPIC,ZOOM_API,RAZOR,PAYPAL,GOOGLE,MAXMIND,SOCIAL ext
    class WF1,WF2,WF3,WF4 ci
```

**The shape, decoded:**

- **One process per concern, not microservices.** Single FastAPI container hosts the API, the scheduler, and the static-file mount. Microservices were rejected at this stage — the team is one + AI; the operational tax of multi-service ops outweighs the (currently nonexistent) scaling benefit. We chose modular monolith with strong layer boundaries (`api/` → `services/` → `repositories/` → `models/`) so that *extracting* a service later is a refactor, not a rewrite.
- **Caddy in front of everything.** Auto-TLS + HTTP/2 + gzip with zero ops. Nginx was the obvious alternative but Caddy's `Caddyfile` is a fifth the size and LetsEncrypt is built-in.
- **State lives in three places, on purpose.** Postgres (authoritative), Redis (volatile cache + rate-limit + pubsub), and a docker named volume (`cpmai-uploads`) for blobs. Backups capture all three.

---

## 3. Request lifecycle (a public read)

```
Browser            Caddy          FastAPI                Redis            Postgres
   │                 │                │                     │                 │
   │── GET /api ────►│                │                     │                 │
   │                 │── proxy ──────►│                     │                 │
   │                 │                │  tenant_id resolve  │                 │
   │                 │                │  (host or JWT) ─────┼────────────────►│
   │                 │                │                     │                 │
   │                 │                │  settings_store ────┤  miss → DB read │
   │                 │                │  (30s TTL cache)    │                 │
   │                 │                │                     │                 │
   │                 │                │  RBAC dep ──────────┼────────────────►│
   │                 │                │  (Depends(get_user))│                 │
   │                 │                │                     │                 │
   │                 │                │  endpoint logic ────┼────────────────►│
   │                 │                │                     │                 │
   │                 │                │  audit_log() write  │                 │
   │                 │                │  (if mutating) ─────┼────────────────►│
   │                 │                │                     │                 │
   │◄── 200 JSON ────┼────────────────┤                     │                 │
```

Three things that are non-obvious:

1. **Tenant is resolved before anything else.** Either from the request host (subdomain → `tenants.host_pattern`) or from the JWT claim. Every query downstream reads `get_current_tenant_id()` — there is no global "current user can see everything" path.
2. **Settings are cached at three levels.** Postgres (authoritative) → Redis (30s TTL, pubsub-invalidated) → per-request memoization. Saves an ORM round-trip per request and lets ops `PATCH /admin/settings` and see the change in <1s across all pods (when we go multi-node).
3. **Audit log is structured prefix.** `auth.login`, `assistant.drift.*`, `zoom.session.created`, `social.run.posted`. The same table backs every operator dashboard, so adding a new dashboard = `SELECT … WHERE action LIKE 'prefix.%'`.

---

## 4. Multi-tenancy as foundation — contract I-1

This was a Day-1 decision and it shapes everything else. Migration `0023_tenants_foundation.py` introduced `tenants` + a `tenant_id` column on every owned table. The contract (`docs/contracts/I-1.md`):

| Rule | Enforcement |
|---|---|
| Every owned row has `tenant_id NOT NULL` | Alembic check in `scripts/preflight.sh` |
| Every query filters by `tenant_id` | Reviewer convention + `get_current_tenant_id()` dep |
| Cross-tenant access requires explicit super-admin role | `get_super_admin_user` dep + audit log |
| Tenant resolution before request handlers | `app/core/tenant.py` ContextVar set in middleware |

**Why this matters for the HoE conversation:** the platform is single-tenant today (one tenant row) but every read/write path is already isolated. Onboarding a second tenant is a config exercise, not a re-architecture. The cost was modest: `tenant_id` on ~25 tables and a small set of helpers.

---

## 5. Data architecture

```mermaid
erDiagram
    tenants ||--o{ users : "owns"
    tenants ||--o{ courses : "owns"
    tenants ||--o{ campaigns : "owns"
    users ||--o{ subscriptions : "has"
    users ||--o{ enrollments : "has"
    plans ||--o{ subscriptions : "fulfils"
    plans }o--o{ courses : "plan_courses (M:N)"
    courses ||--o{ chapters : "groups"
    chapters ||--o{ lessons : "ordered"
    lessons ||--o{ lesson_files : "attachments"
    lessons ||--o{ quiz_questions : "assesses"
    quiz_questions ||--o{ quiz_options : "MCQ"
    course_categories }o--o{ courses : "tagging"
    zoom_sessions ||--o{ zoom_recordings : "captures"
    campaigns ||--o{ campaign_runs : "scheduled"
    rag_documents ||--o{ rag_chunks : "embedded"
    users ||--o{ assistant_logs : "transcripts"
    assistant_logs ||--o| assistant_flagged_turns : "HITL"
    users ||--o{ audit_logs : "actor"
    users ||--o{ payments : "paid by"
    system_settings }|--|| tenants : "scoped (future)"
```

**Decisions worth flagging:**

- **Postgres + pgvector, not a separate vector DB.** Same connection pool, same backup, same migration tool. Latency at our scale is <50ms cosine over ~50k chunks — no Pinecone tax.
- **`JSONB` for evolving shapes** (campaign config, lesson content, settings values). Strict tables for everything queried by predicate. Hybrid keeps Alembic migrations rare for product iteration.
- **No ORM lazy-loading across requests.** Repository layer always returns plain dicts or detached entities. Prevents N+1 surprise and makes the eventual GraphQL/service-extraction step cheap.
- **Soft-delete via `is_deleted`/`deleted_at`** on user-visible content (courses, lessons, users). Hard-delete reserved for explicit GDPR-erasure path (`/api/v1/users/me/data-deletion`).

---

## 6. Runtime configuration — the `settings_store` pattern

This is one of the platform's load-bearing decisions. The single principle: **anything ops should be able to change without a redeploy lives in `system_settings`.**

```mermaid
sequenceDiagram
    participant Admin
    participant API as FastAPI<br/>PATCH /admin/settings
    participant DB as Postgres<br/>system_settings
    participant PUB as Redis<br/>pubsub channel
    participant POD as All backend pods
    participant CACHE as In-process<br/>30s TTL

    Admin->>API: PATCH {"uploads.max_mb": "2048"}
    API->>API: EDITABLE[key].validate(value)
    API->>DB: UPSERT system_settings
    API->>PUB: PUBLISH "settings.invalidated"
    PUB-->>POD: notify
    POD->>CACHE: drop key
    Note over POD,CACHE: Next read goes to DB → Redis → cache
```

Three things keep this safe:

| Concern | Mechanism |
|---|---|
| Arbitrary key writes | `EDITABLE: dict[str, Validator]` whitelist — unknown keys → 422 |
| Type errors at runtime | Each validator returns `(ok, normalized)`; coerces strings before write |
| Secret leakage in GET | `SECRET_KEYS: frozenset` — values masked to last-4 chars in API responses |

There are three sources of truth in priority order: `settings_store.get(...)` > env var > hardcoded default. Code reads through a helper (`_max_upload_bytes()` is a typical example) so adding a key is mechanical:

```python
# uploads.py — read pattern
def _max_upload_bytes() -> int:
    mb = settings_store.get_int("uploads.max_mb", 0)   # 1. runtime override
    if mb <= 0:
        mb = int(os.environ.get("MAX_UPLOAD_MB", "1024"))  # 2. deploy override
    return mb * 1024 * 1024                              # 3. hardcoded floor
```

PR #79 (just deployed) made Zoom credentials + new social handles + the upload cap all hot-editable. Operators rotate Zoom OAuth secrets at 09:00 and the next request picks them up.

---

## 7. Authentication & authorization

```mermaid
graph LR
    GOOGLE["Google One-Tap"] --> AS["auth_service.py"]
    PWD["argon2 password"] --> AS
    AS --> JWT["JWT issuer<br/>access (4h*) + refresh (1d*)<br/>*runtime-tunable"]
    JWT --> DEPS["Dependency chain"]
    DEPS --> ROLE{"role?"}
    ROLE -->|"super_admin"| SUPER["cross-tenant ops"]
    ROLE -->|"admin"| ADMIN["/admin/* gated"]
    ROLE -->|"user"| USER["paid + free paths"]
    ROLE -->|"anon"| ANON["cookie anon_id<br/>(funnel tracking)"]
```

Decisions:
- **No password reset email loop yet** — Google is the primary path; the password fallback is for the bootstrap admin and recovery cases. This is a documented `known-limitations.md` item, scheduled for the auth-hardening PR.
- **Access/refresh TTLs are admin-tunable** (`auth.access_token_expire_minutes` 5–1440, `auth.refresh_token_expire_days` 1–30). This let us tighten the rotation window during a security review without a redeploy.
- **Anonymous tracking is intentional.** A cookie-bound `anon_id` lets us measure funnel drop-off without a login. Cleared on logout to comply with GDPR.

---

## 8. The chat assistant — two flows, one switch

The assistant was the product's origin. It runs two orchestration flows in the same codebase and can switch between them at runtime per request, including a shadow mode for offline comparison. Full deep-dive in `docs/agentic-toggle-architecture.md`; the summary:

```mermaid
graph TB
    REQ["POST /api/v1/chat"] --> GUARD["Guardrails<br/>regex injection · cooldown · daily-cap"]
    GUARD --> ORCH["resolve_flow()"]
    ORCH -->|"legacy"| KW["Keyword classifier"]
    KW --> H1["faq · content · account ·<br/>insights · pmi handler"]
    H1 --> LLM1["1 generation call"]
    ORCH -->|"agentic"| ROUTER["Router LLM<br/>(tool-calling)"]
    ROUTER --> TOOLS["7 tools:<br/>RAG search · user state ·<br/>plan lookup · escalate"]
    TOOLS --> REPLAN{"empty?"}
    REPLAN -->|"yes, max 1"| ROUTER
    REPLAN -->|"no"| SYNTH["Synthesis LLM<br/>(grounded + citations)"]
    LLM1 --> DRIFT["Drift detector<br/>4 heuristic rules"]
    SYNTH --> DRIFT
    DRIFT --> AUDIT["audit_logs"]
```

Switch values for `assistant.flow`: `legacy`, `agentic`, `percent:N` (deterministic per-user cohort), `shadow` (both run, user sees legacy, agentic logged for offline diff). This let us roll out the agentic flow at 10% → 50% → 100% with one PATCH per step and a rollback at the same speed.

---

## 9. LMS subsystem

Courses → chapters → lessons → (files + quiz_questions → quiz_options). Built in PR #6/#7. Notable choices:

- **Plan ↔ Course is M:N** (`plan_courses`). One plan can include multiple courses; one course can ship in multiple plans (e.g. "intro" appears in both Free and Pro).
- **Enrollment is computed, not stored as duplicate state.** A user has access to a course if `(subscription is active AND course ∈ plan_courses[subscription.plan])` OR `(explicit enrollment row exists)`. No drift between "I paid" and "I can see it."
- **File uploads are admin-gated and stream-capped.** Per-request cap evaluated through `_max_upload_bytes()` so the operator can change the limit live. Path is `/{tenant_id}/{YYYY}/{MM}/{uuid}-{safe_name}` — tenant-isolated and date-partitioned for `find` reclaim.
- **`file_object_key` column is already in the schema** — when we swap to R2 in PR #9, the renderer prefers `file_object_key` over the local URL. The migration is data-fill, not schema-change.

---

## 10. Zoom integration

```mermaid
sequenceDiagram
    participant Admin
    participant API as FastAPI
    participant ZAPI as Zoom REST API
    participant ZSDK as Zoom Meeting SDK
    participant Browser
    participant WH as Webhook handler

    Admin->>API: POST /admin/zoom/sessions
    API->>ZAPI: create meeting (Server-to-Server OAuth)
    ZAPI-->>API: meeting_id + join_url
    API->>API: store zoom_sessions row
    Note over Browser: User navigates to /sessions/[id]/live
    Browser->>API: GET signed SDK JWT
    API->>API: HMAC-sign (sdk_key + sdk_secret + ttl)
    API-->>Browser: JWT
    Browser->>ZSDK: join(meeting_id, jwt)
    ZSDK<<->>ZAPI: media
    Note over ZAPI,WH: ~minutes after meeting ends
    ZAPI->>WH: POST /webhooks/zoom (recording.completed)
    WH->>WH: verify signature (HMAC-SHA256 v0)
    WH->>ZAPI: download recording
    WH->>API: store zoom_recordings + write to /uploads
```

Decisions:
- **OAuth Server-to-Server** (not user OAuth) — single host account, admin-issued, lives in `system_settings` as `zoom.oauth_client_id` / `zoom.oauth_client_secret`. Rotatable live (PR #79).
- **Webhook signature is verified before deserialization.** Zoom's `v0` scheme: `HMAC-SHA256(secret, "v0:{ts}:{body}")`. Replay window 5 min.
- **Recordings land in the same `cpmai-uploads` volume** as lesson files. One backup path, one access-control path. They become `LessonFile` rows so the existing player just works.

---

## 11. Social media automation

Built in PR #77. Architecture is intentionally boring:

```mermaid
graph TB
    SCHED["APScheduler<br/>AsyncIOScheduler<br/>(in FastAPI lifespan)"]
    CAMP[("campaigns table<br/>cron + workflow + config_json")]
    RUN[("campaign_runs table<br/>idempotent execution log")]
    RUNNER["WorkflowRunner base<br/>weekly_content · auto_clip ·<br/>repurpose · respond")"]
    LLM["LLMRegistry<br/>(reuses assistant infra)"]
    SOCIAL["LinkedIn · X · Meta APIs"]
    QUEUE["/admin/social-queue<br/>(operator review before post)"]

    SCHED --> CAMP
    CAMP --> RUNNER
    RUNNER --> LLM
    RUNNER --> RUN
    RUN --> QUEUE
    QUEUE -->|"approve"| SOCIAL
```

- **Scheduler runs in-process**, not a separate worker. APScheduler's `AsyncIOScheduler` registers jobs on app startup, persists state in the `campaigns` table. This works to one node; the next step (multi-node) swaps for `APScheduler[Redis]` job store — one-line change.
- **Workflow runners are a base-class hierarchy.** Adding a new workflow = subclass + register. No code change to the scheduler or the admin UI.
- **No auto-post by default.** Generated posts land in `social_queue` for operator review. The `auto_post: true` config flag exists but ships off — a deliberate "humans in the loop" stance for v1.

PR #8 follow-ups (idea library, hashtag library, per-workflow LLM picker, real video gen) are scoped in `pr7-followups.md` §"PR #8 follow-ups".

---

## 12. Payments — dual-rail by currency

```mermaid
graph LR
    USER["User clicks Buy"] --> FX["GeoIP → currency"]
    FX -->|"INR"| RAZOR["Razorpay create_order"]
    FX -->|"USD/EUR/…"| PAYPAL["PayPal create_order"]
    RAZOR --> CHECKOUT_R["Razorpay checkout"]
    PAYPAL --> CHECKOUT_P["PayPal checkout"]
    CHECKOUT_R -.webhook.-> VERIFY_R["verify signature<br/>(HMAC-SHA256)"]
    CHECKOUT_P -.webhook.-> VERIFY_P["verify signature<br/>(PayPal Webhook-ID)"]
    VERIFY_R --> IDEMP["idempotency:<br/>payments.provider_order_id UNIQUE"]
    VERIFY_P --> IDEMP
    IDEMP --> GRANT["grant subscription<br/>+ audit_log"]
```

- **Currency selection driven by MaxMind GeoIP** (`mmdb` file bind-mounted; refreshed by a cron). Override allowed in the UI.
- **`provider_order_id` is a UNIQUE constraint.** Webhook double-delivery is a known pattern — DB enforces idempotency, code doesn't.
- **Auto-enrollment is a TODO** (PR scoped in `pr7-followups.md` Bucket D). Right now the payment grants a subscription; the LMS side reads subscription → plan → courses, so the user sees the course. The TODO is to also write an explicit `enrollments` row for analytics.

---

## 13. File storage — local today, R2 tomorrow

```mermaid
graph LR
    UI["Admin uploader"] --> EP["POST /admin/uploads"]
    EP --> CAP["_max_upload_bytes()<br/>(live from settings)"]
    EP --> SAN["sanitise filename<br/>(strict regex)"]
    EP --> MIME["MIME allowlist"]
    EP --> STREAM["stream to disk<br/>64 KB chunks"]
    STREAM --> VOL[("cpmai-uploads volume<br/>tenant/year/month/uuid-name")]
    EP --> ROW["LessonFile row<br/>file_url + file_object_key"]
    ROW --> RENDER{"file_object_key?"}
    RENDER -->|"set"| R2["R2 / S3 (PR #9)"]
    RENDER -->|"null"| LOCAL["/uploads/* via StaticFiles"]
```

Why this stays correct under load:
- **Stream, don't slurp.** UploadFile is async; the per-chunk size check aborts before we fill disk.
- **Named volume survives deploys.** `cpmai-uploads` is referenced by both compose files. Pre-deploy hook tars it to `/var/backups`.
- **Path traversal is impossible.** Filename regex strips `..` and slashes; `relative_to(UPLOAD_ROOT)` enforced on delete.
- **R2 swap is a flag, not a fork.** `file_object_key` column already exists.

---

## 13b. Visitor Insights v2 — funnel + page-level analytics

Built on the same `journey_events` table the funnel events already used; the SPA now also writes `page.view`, `page.heartbeat`, `page.exit`, `scroll.depth`, `cta.click`, `session.start`, `session.end` via a batched `POST /api/v1/track` endpoint.

```mermaid
graph LR
    SPA["Next.js SPA<br/>src/lib/tracker.ts<br/>route hook · heartbeat ·<br/>scroll watcher · CTA delegation"] --> POST["POST /track<br/>(batched, sendBeacon on exit)"]
    POST --> NORM["path normaliser<br/>+ UA parser + GeoIP + PII strip"]
    NORM --> EMIT["emit_event()<br/>→ journey_events"]
    EMIT --> LIVE["live aggregation<br/>tenant + event + day index"]
    EMIT --> ROLLUP["nightly rollup<br/>visitor_insights_daily<br/>(off by default)"]
    LIVE --> DASH["/admin/insights<br/>overview · top pages · funnel ·<br/>session drilldown · GDPR anonymise"]
    ROLLUP --> DASH
```

**Auto-scale property (zero-maintenance for new routes):**
The dashboard groups by route TEMPLATE (`/courses/[slug]`) not raw URL. We derive the template client-side using Next.js's `useParams()` — for any route the App Router knows how to match, the tracker replaces dynamic segment values with `[paramName]` automatically. Adding a new `app/instructors/[name]/page.tsx` page rolls up to `/instructors/[name]` from the day it deploys, with zero server change. A drift-protection vitest walks every `app/**/[*]` directory and asserts derivation works for each, so a future PR can't silently regress this.

The server keeps a generic fallback normaliser (collapses numeric ids, UUIDs, and 12+-char slugs with digits to `[*]`) for the rare events the backend emits with a raw path (referrer fields, lifecycle events).

**Levers exposed to ops (live-editable via `/admin/settings`):**
- `tracking.enabled` — master kill switch
- `tracking.sample_rate` — 0.0–1.0 per-batch sampling
- `tracking.rollup_enabled` — flip dashboard to pre-aggregated reads when journey_events growth threatens index health

**Scalability path:**
- Today: dashboards read live, ~230k rows/7d on a single index scan
- Day-1 future-proofing: `visitor_insights_daily` table created in migration 0032, populated by nightly APScheduler job (idle until `tracking.rollup_enabled=true`)
- Beyond: sampling + rollup means we don't need ClickHouse / column store at 1–10M events/day

**GDPR:** `POST /admin/insights/anonymize/{anon_id}` nulls anon_id/session_id/ua/city on every matching row but keeps the events — aggregate counts don't shift.

---

## 14. Observability

```mermaid
graph TB
    APP["App code"] --> AUDIT["audit_log(action, payload)<br/>structured prefix"]
    APP --> JSONL["structured JSONL<br/>backend/logs/app.jsonl"]
    APP --> ASLOG["assistant_logs<br/>(per chat turn)"]
    APP --> DRIFT["drift detector<br/>4 heuristic rules"]
    APP --> DISK["disk-usage endpoint<br/>/admin/observability/disk"]

    AUDIT --> PG[("audit_logs table")]
    DRIFT --> PG
    ASLOG --> PG
    DISK --> METRICS["volume sizes · backups age ·<br/>reclaimable items"]

    PG --> DASH1["/admin/assistant-drift"]
    PG --> DASH2["/admin/chat-history"]
    PG --> DASH3["/admin/leads"]
    PG --> DASH4["/admin/observability"]

    JSONL -.scheduled.-> SENTRY["(planned)<br/>Sentry / Logflare"]
```

**Centralised logging plan (next infra PR):**
1. JSONL → Vector → Loki (or Sentry for errors).
2. `console.error` calls in the SPA wired to the same pipeline.
3. Disk-usage webhook fires at 80% of `cpmai-uploads`, 50 GB of backups.

What we have *today* is the audit log + per-turn assistant log + drift detector + disk metrics. The operator can see what happened; the next step is alerts and external aggregation.

---

## 15. CI/CD pipeline

```mermaid
graph TB
    DEV["git push"] --> HOOK{"pre-push hook"}
    HOOK -->|"scripts/preflight.sh"| PRE["localhost validation:<br/>backend tests · frontend tests<br/>· ruff · eslint · TS check ·<br/>docker prod build (Linux/WSL)"]
    PRE -->|"fail"| BLOCK["push blocked"]
    PRE -->|"pass"| PUSH["push to origin"]

    PUSH --> PR{"PR opened?"}
    PR -->|"yes"| WF_BE["backend-ci.yml<br/>pytest + alembic upgrade head"]
    PR --> WF_FE["frontend-ci.yml<br/>vitest + lint + TS + build"]
    PR --> WF_SEC["security-scan.yml<br/>gitleaks + npm audit + pip-audit"]

    WF_BE --> GATE{"all green?"}
    WF_FE --> GATE
    WF_SEC --> GATE

    GATE -->|"yes + main"| WF_DEPLOY["deploy.yml<br/>1. Pre-deploy backup<br/>(DB + uploads tarball)<br/>2. Build + tag :latest + :previous<br/>3. SSH → scripts/vps/deploy.sh<br/>4. compose up -d<br/>5. wait health<br/>6. smoke test"]

    WF_DEPLOY --> SMOKE{"smoke pass?"}
    SMOKE -->|"no"| ROLLBACK["auto-rollback:<br/>retag :previous → :latest<br/>+ DB restore"]
    SMOKE -->|"yes"| DONE["deployed"]
```

Quality gates in order of execution:

| Stage | Tooling | What it catches |
|---|---|---|
| Pre-push (local) | `scripts/preflight.sh` | Fast feedback before CI burn — runs backend pytest, frontend vitest, ruff, eslint, TypeScript check, and (Windows-WSL aware) a real `docker build -f Dockerfile.prod` so the deploy-context bugs surface locally |
| Backend CI | pytest + `alembic upgrade head` from empty DB | Migration drift, test regressions |
| Frontend CI | vitest + lint + TypeScript + `next build` | Build-time errors, peer-dep issues, env-var traps |
| Security scan | gitleaks (secrets), npm audit, pip-audit | Committed credentials, known CVEs |
| Deploy gate | All of the above must pass on `main` | One broken gate blocks every deploy — see `docs/feedback_ci_discipline.md` |

The deploy gate is sacred and is documented in `MEMORY.md` precisely because breaking it has burned us. Touching `deploy.yml`, migrations, or `alembic env.py` requires grep'ing the lessons doc first.

---

## 16. Deployment & rollback

`scripts/vps/deploy.sh` does this every time:

1. **Pre-deploy backup**: `pg_dump` + `tar cf uploads.tar /var/lib/docker/volumes/cpmai-uploads/_data`. Both `chmod 0600`, kept for 14 days.
2. **Re-tag current `:latest` → `:previous`** for both images.
3. **Build new images** (multi-stage `Dockerfile.prod`): deps → builder → runner. `--target runner` keeps the final image tiny (~250 MB frontend, ~400 MB backend).
4. **`docker compose -f docker-compose.prod.yml up -d`** with health-check gating.
5. **Smoke test** against `https://api.cpmaiexamprep.com/health`.
6. **On any failure**: auto-rollback. Retag `:previous` → `:latest`, `compose up -d`, restore DB from the pre-deploy dump if migrations ran.

Asymmetric image retention: 72h for tagged images, 24h for builder cache (`docker buildx prune`). Logs the size delta after each build so the operator can spot a runaway dependency.

**Drift discipline** (also in `MEMORY.md`): compose files, image tags, and migrations must converge on prod. Past failures came from "I changed compose locally but the VPS never re-pulled." The deploy script now always rebuilds — no `if newer` shortcut.

---

## 17. Migration discipline — contracts M-1/M-2/M-3

| Contract | Rule | Why |
|---|---|---|
| M-1 | Additive only (no `DROP`, no `ALTER … NOT NULL` on existing data) | A failed deploy leaves the old container running against the new schema — additive changes are forward-compat |
| M-2 | One migration per logical change | Bisect across migrations works, revert is surgical |
| M-3 | Always tested with `alembic upgrade head` from empty DB in CI | Catches the missing-revision-id and out-of-order branches |

Backfills go in a separate migration that runs *after* the schema migration so the new code can deploy first, then the data catches up.

---

## 18. Security posture

| Surface | Control |
|---|---|
| Secrets in DB | `SECRET_KEYS` frozenset → masked to last-4 in `GET /admin/settings` |
| Secrets in repo | gitleaks in CI; `.gitleaksignore` for legitimate fixtures |
| RBAC | `Depends(get_admin_user)` / `get_super_admin_user`; tested negatively (the test suite asserts non-admin → 403) |
| Webhook auth | HMAC verification before deserialization (Zoom v0, Razorpay X-Razorpay-Signature, PayPal Webhook-ID) |
| Path traversal | Filename regex + `relative_to(UPLOAD_ROOT)` on every read/write |
| MIME spoofing | Server-side allowlist; size cap evaluated mid-stream |
| Injection (chat) | Guardrails layer — regex + length + Redis-backed cooldown + daily cap |
| GDPR | `/api/v1/users/me/data-export` + soft-delete with PII redaction; hard-delete reserved |
| TLS | Caddy auto-LetsEncrypt; HTTP→HTTPS redirect; HSTS |
| Backups | `chmod 0600` on env tar + uploads tar (PII inside) |

The Privacy/Terms pages were a documented gap (footer 404'd) and were fixed in PR #2 of the operator-readiness work.

---

## 19. Engineering standards — the discipline layer

These are the rituals that turn "code works on my machine" into "deploy at 5pm Friday without a Slack channel of fear."

1. **Localhost-first validation.** Preflight runs the Docker prod build on Windows-WSL. Caught the `.npmrc` dotfile bug (Dockerfile `COPY package*.json ./` missed it) before the deploy ever ran.
2. **Three-step ritual for any new editable setting.** Update `EDITABLE` validator → add row to `default_settings.json` seed → extend the drift integration test. Catches the "I added a setting but it's invisible in the admin UI" class of bug (which was the PR #79 hotfix).
3. **Cherry-pick from main, never push to a merged branch.** When a follow-up fix is needed after merge, branch from `origin/main`, cherry-pick, push.
4. **CLAUDE.md / MEMORY.md as living docs.** Recurring failure modes (deploy drift, CI discipline, prod deploy mechanics) are documented inline so the next change touches them with eyes open.
5. **Audit log first, dashboard later.** Every notable action writes `audit_log(...)` before any UI exists. When the operator asks "did the webhook actually fire at 09:14?", the answer is a SQL query.
6. **Tests pin the behaviour, not the implementation.** Round-trip tests on `/admin/settings`, MIME-allowlist tests on `/admin/uploads`, RBAC negative tests on every admin endpoint.

---

## 20. Scalability roadmap — swap-not-rewrite

```mermaid
graph LR
    NOW["Today<br/>Single VPS<br/>1 backend pod<br/>local uploads<br/>in-process scheduler"]
    NOW -->|"Step 1"| MULTI["Multi-pod backend<br/>(same VPS, replicas: 3)<br/>+ APScheduler[Redis]"]
    MULTI -->|"Step 2"| R2["R2 / S3 for uploads<br/>(toggle via file_object_key)"]
    R2 -->|"Step 3"| LB["Caddy → load balancer<br/>+ separate DB host"]
    LB -->|"Step 4"| MULTI_REGION["Multi-region<br/>Postgres logical replication<br/>+ R2 multi-region"]
    LB -->|"Step 5"| EXTRACT["Extract hot services:<br/>chat-orchestrator<br/>social-runner"]
```

Each step is unblocked by a Day-1 decision:

| Step | Unlocked by |
|---|---|
| Multi-pod backend | Settings cache invalidation already goes through Redis pubsub |
| R2/S3 uploads | `file_object_key` column shipped in PR #6 |
| LB + DB split | No filesystem-coupled state in the API tier (uploads are the only one, and they're behind a flag) |
| Multi-region | Multi-tenancy contract I-1 means tenants are already pinned to a region-able key |
| Service extraction | `api/` → `services/` → `repositories/` layering; orchestrator doesn't reach into models |

---

## 21. What we say "no" to (and why)

| Tempting | Why we declined |
|---|---|
| Microservices on Day 1 | Operational tax > scaling benefit at 1 team / 1 VPS |
| Kubernetes | Docker Compose covers the current node count; K8s when we cross 3 nodes |
| Pinecone / Weaviate | pgvector is fast enough, one backup, one connection pool |
| Separate worker for the scheduler | APScheduler in-process is fine to one node; Redis job store is the swap |
| Auto-post social content | Operator-in-the-loop reviewed every post; trust before automation |
| Bespoke admin UI framework | Plain Next.js + Tailwind; consistent with the public site |
| Custom auth | Google one-tap + JWT + argon2; no rolled crypto |
| Premature R2 swap | Local disk on the VPS is correct until the second node arrives |

---

## Appendix A — directory map

```
backend/app/
  api/v1/endpoints/      ← routes; admin/* gated by Depends(get_admin_user)
  core/                  ← deps, exceptions, tenant resolver, settings_store, audit
  models/                ← SQLAlchemy models (one file per aggregate)
  schemas/               ← Pydantic request/response shapes
  services/              ← business logic; called by endpoints, calls repositories
  repositories/          ← data access; one per aggregate
  utils/                 ← shared helpers (LLM registry, embeddings, FX)

backend/migrations/      ← alembic; additive-only per M-1
backend/seeds/           ← default_settings.json + bootstrap data
backend/tests/           ← unit + integration; one file per aggregate

frontend/src/app/        ← Next.js App Router
  admin/*                ← admin pages; bounce non-admins client-side + server-side
  (public)               ← marketing + LMS public
  sessions/[id]/live     ← Zoom SDK embed

scripts/                 ← bootstrap.sh, preflight.sh, upgrade.sh
scripts/vps/             ← deploy.sh, backup.sh, restore.sh, install_*.sh, provision.sh

.github/workflows/       ← backend-ci, frontend-ci, security-scan, deploy

docs/                    ← architecture, contracts, lessons, backlog
docs/contracts/          ← I-1 multi-tenancy, M-1/2/3 migrations, others
```

## Appendix B — links to the deeper docs

- `docs/agentic-toggle-architecture.md` — chat assistant flows
- `docs/design-decisions.md` — major levers + why each was chosen
- `docs/known-limitations.md` — gaps + workarounds
- `docs/deployment.md` — lifecycle + rollback narrative
- `docs/vps-deployment-lessons.md` — every prod failure mode + fix
- `docs/feedback_ci_discipline.md` — what NOT to do to the deploy gate
- `docs/feedback_infra_drift.md` — compose/image/migration convergence
- `docs/contracts/I-1.md` — multi-tenancy contract
- `docs/backlog.md` — current + future work
- `docs/pr7-followups.md` — operator-surfaced gaps, prioritised
