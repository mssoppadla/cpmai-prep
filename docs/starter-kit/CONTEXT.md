# CONTEXT — what we are building and how it is shaped

You (Claude) are building an exam-preparation SaaS in the mold of
cpmaiexamprep.com. This file is the product brief + architecture contract.
Read it fully before writing any code. When a detail is not specified
here, prefer the simplest option consistent with these conventions and
say so in the commit message — do not invent new architecture.

## 1. Product in one paragraph

Learners sign up (email/password or Google), take timed mock exams
assembled from a question bank, and get a scored review broken down by
certification domain, with per-option reasoning and explanations. An AI
tutor answers questions grounded in site content. Admins manage
questions (single + bulk Excel), exam sets, courses/lessons with gated
video, CMS pages, pricing/payments, leads, and AI configuration —
everything through an admin console, nothing by SSH. The public site is
SEO-rendered; the whole thing runs on one VPS behind Caddy with CI-gated
deploys.

## 2. Stack (fixed — do not substitute)

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2.
- **DB**: PostgreSQL 16 with **pgvector** (RAG embeddings). Redis for
  cache/quotas.
- **Frontend**: Next.js (App Router) + TypeScript + Tailwind. Public pages
  server-rendered for SEO; app pages client-side with a typed API client.
- **Tests**: pytest (unit + integration; integration uses in-memory SQLite
  + fakeredis so no services are needed), vitest for frontend logic,
  `tsc --noEmit` as a gate.
- **Infra**: docker-compose (postgres, redis, backend, frontend), host-level
  Caddy for TLS, GitHub Actions CI, single Ubuntu VPS.

## 3. Domain model (the heart — model this carefully)

- **Topic / phase**: the 6 CPMAI phases (BU, DU, DP, MD, EV, DE). Seeded,
  fixed.
- **ECO domain**: D-I…D-V with exam weights 15/26/26/16/17 (%). Kept as a
  **code-level registry** (dataclass tuple), not a DB table — it changes
  only when the certification body changes it. The registry resolves
  legacy spellings (name/slug/"D-I Trustworthy" free-text) to canonical
  codes; writes normalize to codes. D-I (Trustworthy AI) is cross-cutting:
  it maps to no single phase.
- **Question**: stem, topic (phase), domain code, difficulty,
  single/multi choice, 2–6 options each with `is_correct` + per-option
  `reasoning`, plus an overall `explanation`. Admin CRUD + bulk
  Excel round-trip (export with ids → edit → upload updates in place;
  blank id = create; `exam_sets` column syncs memberships by slug).
- **Exam set**: named, slugged collection of questions, time limit,
  passing score, free/premium.
- **Exam session (attempt)**: per user (or anon token) per set; expiry
  timestamp; answer rows store selected letter(s) + `marked_for_review`.
  **Time-up never voids a sitting**: submit accepts expired attempts,
  and read paths auto-finalize them — captured answers always become a
  result.
- **Result snapshot (load-bearing pattern)**: at submit, the FULL review
  payload (stems, options, correct flags, reasonings, verdicts, domain,
  review flags) is frozen into a JSON column on the session. Results are
  served from the snapshot forever. This is what makes questions safely
  editable/deletable after candidates have taken exams. Legacy attempts
  without snapshots fall back to live reconstruction.
- **Domain practice**: from a result, drill only one domain's questions
  of that set (separate session type, `practice_domain` column).
- **Results UX**: score banner with tappable filters (correct/incorrect/
  unanswered/marked-for-review) composing with domain filter chips.

## 4. AI subsystem (see AI-INTEGRATION.md for depth)

Provider registry (DB-configured: OpenAI/Anthropic/stub) → intent
classifier → handlers (RAG answer, exam insights, pricing, live-session
info) → guardrails (site-scope system prompt, daily quotas per
user/anon, admin per-user overrides) → logging (every turn stored,
flaggable) → drift + observability dashboards.

## 5. Cross-cutting conventions (enforced in review)

- **Error envelope**: every API error is
  `{"error": {"code", "message", "fields?", "request_id"}}`. Frontend has
  one typed `ApiError`.
- **Types mirror schemas**: `frontend/src/types/api.ts` hand-mirrors
  Pydantic schemas exactly.
- **Auth**: JWT access (4h) + refresh; roles user/admin/super_admin; admin
  router wrapped in one dependency. Anonymous exam access via
  `X-Anon-Token` where the product allows it.
- **Audit everything**: one `audit_log(db, user_id, action, metadata)`
  helper; every admin mutation and every significant user event calls it.
- **Multi-tenancy-ready**: `tenant_id` column on content tables, default
  tenant id=1 seeded.
- **Registries over tables** for certification-fixed vocabularies;
  **snapshot-on-write** for anything users must be able to revisit
  unchanged; **read-time resolution + write-time normalization** for
  legacy data.
- **Migrations**: additive and reversible when possible; data migrations
  are self-contained (no app imports), idempotent, and no-op on empty
  DBs; `transaction_per_migration=True` in alembic env. The chain is
  NOT runnable from an empty DB by design — fresh installs do
  `create_all` + `alembic stamp head` (document this in the repo).
- **Media**: uploads under `/uploads` on a named volume; images public,
  video/PDF gated by short-lived signed tokens; Range/206 streaming.
- **Payments**: provider registry (Razorpay + PayPal sandbox), plans →
  subscriptions, webhook verification, GST modes, UTM attribution
  stamped at order creation.
- **Seeds**: idempotent seeder (skip-if-exists) run on every deploy;
  every `settings_store.get_*` key must exist in `default_settings.json`.

## 6. Quality bars (non-negotiable)

- Zero failing tests, including pre-existing ones — "it was already
  broken" is not accepted.
- Every feature lands with regression tests in the standard pytest/vitest
  trees (CI runs the whole tree; nothing is opt-in).
- Every PR verified live in a browser before it is opened, not just by
  tests.
- Accessibility: never encode state by color alone (shape/border/label
  cues alongside), a lesson embedded throughout the results UI.
