# BUILD PLAYBOOK — empty repo → production, in ten phases

Each phase has: a **Decisions box** (fill it in before prompting — these
are the only things Claude can't decide for you), a **prompt** to give
Claude verbatim, a **definition of done**, and **verify commands**. Do the
phases in order; each leaves a deployable, tested system.

General prompt prefix for every phase (Claude Code):

> Follow docs/starter-kit/SKILL.md. Context is docs/starter-kit/CONTEXT.md.
> Now execute the phase below. Work until its Definition of Done is met,
> verifying in the browser before you finish.

---

## Phase 0 — Skeleton & rails

**Decisions:** product name · repo name · Python/Node versions (default
3.12/20) · license.

**Prompt:** Scaffold the monorepo: `backend/` (FastAPI app factory,
health endpoint, error-envelope exception handlers, structured JSON
logging, settings via pydantic-settings reading `.env`), `frontend/`
(Next.js App Router + Tailwind + typed API client with the ApiError
envelope), `docker-compose.yml` (postgres:16 with pgvector image, redis,
backend, frontend), `.env.example` for both, pytest + vitest wiring with
one passing test each, GitHub Actions CI running backend tests, tsc,
vitest on every PR, pre-push hook running the same suite. README with
the fresh-DB bootstrap note (create_all + stamp head).

**Done when:** `docker compose up` serves both apps; CI green on first
PR; `curl /health` returns the envelope-consistent payload.

**Verify:** `pytest -q`, `npm run test`, `npx tsc --noEmit`, browser on
`localhost:3000`.

---

## Phase 1 — Identity, roles, audit

**Decisions:** Google OAuth? (needs a Google Cloud client id) · session
lengths (default access 4h / refresh 7d) · bootstrap admin email.

**Prompt:** Implement auth: email/password signup+login with lockout
counters, JWT access+refresh, roles user/admin/super_admin, `/users/me`,
admin users list with soft-delete (GDPR-style redaction), bootstrap
super-admin seeded from env. Add `audit_log()` helper + `audit_logs`
table (tenant_id column, default tenant seeded) and call it from every
mutation. Optional Google sign-in (credential exchange server-side).
Admin layout in frontend with role-gated routing; login/signup pages.

**Done when:** signup→login→me works in browser; admin sees users list;
audit rows appear; lockout after N failures; all under test.

---

## Phase 2 — Question bank & domain registry

**Decisions:** your certification's phase list and domain list + weights
(CPMAI defaults are in CONTEXT.md §3) · difficulty levels.

**Prompt:** Seed topics (phases). Build the ECO-domain code registry
(codes, names, slugs, weights, phase mappings) with a tolerant
`get()` resolver (code/name/slug/punctuation-and-legacy-tolerant) and
write-time canonicalization in the admin schema. Question + options
models per CONTEXT.md, admin CRUD with strict validation (2–6 options,
exactly-one/≥2-correct rules), list with filters (set/domain/phase/
search/tag-state), bulk Excel: template with dropdown validation, export
with ids + memberships, upload that creates/updates per-row with
per-row error reporting. Delete must clean referencing rows (safe once
Phase 3 snapshots exist — until then block deletion of attempted
questions), plus bulk-delete with select-all-filtered UI.

**Done when:** an Excel round-trip (export → edit → upload) updates in
place; domain always stored as canonical code; upload parser has zero
errors on the exported file.

---

## Phase 3 — Exam engine (the crown jewel)

**Decisions:** attempt rules (one in-progress per set?) · anonymous
attempts allowed on free sets? · passing score default.

**Prompt:** Exam sets admin + public listing. Attempt lifecycle: start
(resume in-progress; create answer rows; backfill rows for questions
added mid-sitting), save-answer (single vs multi shape enforcement,
`marked_for_review`), countdown timer in UI, submit that scores by
exact-set match and **freezes the full result snapshot** (CONTEXT.md §3)
including review flags. Time-up: client auto-submits at zero with
retry; server accepts expired submits, clamps reported time, and
auto-finalizes timed-out sittings on any read — a sitting is never
voided. Results page: score banner with tappable
correct/incorrect/unanswered/marked filters composing with domain
chips, per-domain breakdown bars with weights, per-question review
cards (options, reasonings, explanation, review badge). Domain practice
drills from the breakdown. Attempt history. Admin attempt viewer
(same review, admin-gated).

**Done when:** editing/deleting a question after an attempt does NOT
change that attempt's review (snapshot test proves byte-stability); a
force-expired attempt still yields a captured result; all filters
compose.

---

## Phase 4 — AI tutor with guardrails (see AI-INTEGRATION.md)

**Decisions:** LLM provider(s) + model tier · daily quotas
(anon/authenticated) · assistant scope statement (what it must refuse).

**Prompt:** Implement AI-INTEGRATION.md end-to-end: provider registry
(DB-configured, stub provider for tests/CI), intent classifier,
handlers (RAG answer over site corpus, exam-insights over the user's own
attempts, pricing/live-session info), pgvector ingestion pipeline with
reindex hooks on content CRUD, guardrailed system prompt, Redis-backed
daily quotas with per-user admin override, full turn logging with
admin flagging, drift dashboard, observability counters.

**Done when:** the tutor answers site questions with citations from the
corpus, refuses out-of-scope prompts, hits quota limits correctly, and
every turn is inspectable in admin.

---

## Phase 5 — Payments & plans

**Decisions:** providers (Razorpay/PayPal/both) · plans + prices · tax
mode (e.g. GST inclusive/added) · sandbox keys ready in `.env`.

**Prompt:** Payment-provider registry with sandbox implementations,
plans admin (which exam sets/courses a plan unlocks), checkout flow,
webhook verification + idempotent event handling, subscriptions with
expiry, premium gating on sets/courses (402 envelope → pricing page),
offer codes, UTM columns stamped at order creation, payments admin with
provider test buttons.

**Done when:** a sandbox purchase unlocks premium content end-to-end and
the webhook replay is idempotent; failed webhooks visible in admin.

---

## Phase 6 — CMS, courses, gated media

**Decisions:** course structure (chapters/lessons?) · which media types
gated.

**Prompt:** Content pages (block editor JSON, nav visibility/order,
publish flags, SSR public rendering with SEO metadata — no
last-updated display). Courses → chapters → lessons with video uploads:
media stored on a named volume, images public, video/PDF behind
short-lived signed tokens with Range/206 streaming; lesson progress
tracking feeding user insights.

**Done when:** an admin-authored page appears in public nav (SSR HTML
contains content); an unauthorized video URL fails while the tokened one
streams with seek.

---

## Phase 7 — Growth: leads, email, tracking

**Decisions:** lead capture points · email provider (SMTP creds) ·
consent copy.

**Prompt:** Leads model + capture endpoints (source enum), contacts
admin, journey-event tracker (page dwell, UTM persistence,
consent-gated), email templates + automation engine (trigger on events
like exam.submitted, cooldowns, suppression list), admin queues.

**Done when:** submitting a mock exam enqueues the configured email
(visible in outbox admin) and journey events show in user insights.

---

## Phase 8 — Observability & AI metrics

**Prompt:** Implement the metrics/observability section of
AI-INTEGRATION.md: request logging middleware with request-ids,
error-rate and latency panels, assistant metrics (tokens, cost,
latency, deflection, flag rate, drift evals), daily rollups, admin
observability page. Wire a scheduled drift-eval run with a stored
golden set.

**Done when:** you can answer "what did the AI cost yesterday and did
quality move?" from the admin UI alone.

---

## Phase 9 — Production (see DEPLOYMENT.md)

**Decisions:** VPS provider/size · domain name · DNS host · backup
retention.

**Prompt:** Write `scripts/vps/provision.sh` (user, ufw **80/tcp,
443/tcp AND 443/udp**, fail2ban, docker), `install_app.sh` (fresh DB
bootstrap path), `deploy.sh` (fetch-with-retry, pre-deploy backup,
image tagging for rollback, migrations, seeder, smoke tests with a
dedicated smoke admin, auto-rollback trap), host Caddy config (apex +
api subdomain, security headers, access logs), GitHub Actions deploy
workflow with migration-drift gate (bootstrapped schema + `alembic
check` + `upgrade head`) and manual production approval. Follow
DEPLOYMENT.md's lessons — they are pre-paid tuition.

**Done when:** a merge to main deploys hands-free, a forced failure
auto-rolls back, backups restore, and the site serves with HTTP/3.

---

## Customizing later (Mode C)

Small changes never need the playbook — just: *"Per starter-kit
conventions: <change>"*. For anything touching migrations, payments, or
deploy scripts, remind Claude to re-read SKILL.md's migration
discipline first.
