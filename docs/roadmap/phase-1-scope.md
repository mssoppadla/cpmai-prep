# Phase 1 — Scope, Out-of-Scope, and Acceptance Criteria

**Status**: locked 2026-05-19
**Phase duration**: ~6 weeks of build + 4 weeks of validation
**Related**: `docs/contracts/multi-tenancy-and-saas-integration.md`, `docs/roadmap/phase-2-backlog.md`, `docs/roadmap/validation-gates.md`

## What Phase 1 Delivers

Six weeks of focused work that:

1. Enhances CPMAI Prep with three new feature areas (CMS, LMS, social automation)
2. Builds multi-tenant-ready foundations (per the contract) so Phase 2
   can land without refactor
3. Maintains 100% backward compatibility for existing CPMAI users

This document is the canonical reference for what Phase 1 includes,
what it explicitly excludes, and how we know it's done.

---

## ✅ IN SCOPE

### Feature group 1: CMS — admin-editable content pages

- New table: `content_pages` with single JSONB `blocks` column (per contract Q2)
- Block editor using BlockNote (https://blocknotejs.org)
- Block types supported:
  - heading (h1/h2/h3)
  - paragraph (rich text with bold, italic, code, links)
  - table (headers + rows, drag-to-reorder rows)
  - video (YouTube embed with click-to-load privacy facade)
  - callout (info/tip/warning/success variants)
  - list (ordered/unordered)
  - CTA button (label + URL + variant)
  - divider
  - image (with caption, width control)
  - code (syntax-highlighted)
  - quote (text + author)
- Drag-and-drop block reordering
- Rich text features: bold, italic, code, links, tables with headers,
  emoji picker, colour picker
- Per-page `nav_visibility` enum (per contract Q3):
  - `always` — visible to all (anon, authenticated, subscribed)
  - `authenticated` — only signed-in users see the nav link
  - `subscribed` — only paid subscribers see the nav link
  - `hidden` — page exists but not in nav (still accessible by direct URL)
- AI-assisted block generation via OpenAI (existing LLMRegistry):
  - "Generate page from prompt" — produces a block list
  - "Fill block with AI" — fills one block given context
  - "Improve this block" — rewrite shorter / longer / friendlier / formal / fix grammar
- Public renderer at `/study-guide` and `/study-guide/[slug]` routes
- Admin UI under `/admin/content-pages`
- Header nav integration via `GET /cms/v1/nav` (server-filtered by auth state)

### Feature group 2: LMS — courses, chapters, lessons

- New tables:
  - `courses` (slug, title, description, cover image, price, enrollment type)
  - `chapters` (course_id, title, position, sequencing rules)
  - `lessons` (chapter_id, type, title, video_url, duration, free_preview flag)
  - `enrollments` (user_id, course_id, source, enrolled_at, expires_at)
  - `lesson_progress` (enrollment_id, lesson_id, started_at, completed_at, last_position_seconds)
- Course/chapter/lesson hierarchy with admin builder UI
- Video lesson support (pre-recorded, hosted on Cloudflare R2 or Stream)
- Plyr video player with progress tracking
- Lesson completion + course progress percentage
- Subscription-gated access (extends existing paywall logic via new helpers)
- Free preview lessons (configurable per lesson)
- Quiz lessons (reuse existing Question/ExamSession model from CPMAI)
- Certificate placeholder (PDF generation deferred to Phase 2 polish)
- User UI:
  - `/courses` — course catalog
  - `/courses/[slug]` — course detail with curriculum
  - `/courses/[slug]/lessons/[lid]` — lesson player
- Admin UI under `/admin/courses`

### Feature group 3: Zoom — live sessions + recordings

- New tables:
  - `zoom_sessions` (course_id?, title, scheduled_at, duration_minutes, zoom_meeting_id, host_config)
  - `recordings` (zoom_session_id, r2_object_key, duration_seconds, ready_at)
- Zoom Meeting SDK embedded in cpmaiexamprep.com (no portable URLs)
- Per-session JWT signed by backend, locked to:
  - user identity
  - specific session
  - 30-minute TTL
- Admin controls (set at meeting creation):
  - Mute on entry
  - Allow/disallow participant self-unmute
  - Allow/disallow participant video toggle
  - Enable/disable chat + private chat
  - Waiting room toggle
  - Lock meeting toggle (no new joiners after start)
  - Auto-recording to cloud
- Recording auto-downloaded to Cloudflare R2 via Zoom webhook
- Signed-URL playback for recordings (1-hour TTL, single-use)
- User UI:
  - `/sessions` — My Sessions (upcoming + past, subscription-gated)
  - `/sessions/[id]/live` — live join (Zoom SDK embed)
  - `/sessions/[id]/recording` — recording playback
- Admin UI under `/admin/sessions`

### Feature group 4: Social automation — campaigns

- New tables:
  - `campaigns` (tenant_id, name, schedule_cron, workflow_type, config_json, active)
  - `campaign_runs` (campaign_id, started_at, status, generated_content, posted_at, error)
- APScheduler-based campaign scheduling (cron expressions)
- Workflow runners (plain Python — no n8n, no external workflow engine):
  - "Generate weekly content" — OpenAI text → Pictory video → Buffer post
  - "Auto-clip long video" — Whisper transcript + OpusClip API for shorts
  - "Course session reminder" — 24h before Zoom session → AI post + email
  - "Recording published" — Zoom webhook → trailer clip → social post
- Integrations:
  - OpenAI (text + Whisper transcripts)
  - OpusClip API (auto-clip long videos into shorts)
  - Pictory or InVideo API (text-to-video)
  - Buffer (multi-platform scheduling via official APIs only — LinkedIn ban-risk mitigation)
  - ElevenLabs (optional voice narration)
- Admin UI under `/admin/campaigns`
- All posting via Buffer's official APIs — NEVER call LinkedIn API directly

### Multi-tenant foundations (the contract)

- New `tenants` table seeded with CPMAI as id=1
- `tenant_id` column on every new table (default 1)
- `tenant_id` column on `audit_logs` (per contract Q1)
- `app/core/tenant.py` with `get_current_tenant_id()` stub
- Optional `tenant_id` claim on JWT (defaults to 1)
- Two-tier `settings_store` lookup (tenant-scoped → global fallback)
- `audit_log()` accepts optional `tenant_id` kwarg
- R2 storage paths prefixed by `tenants/{id}/...`

### Infrastructure

- Cloudflare R2 for video/asset storage (₹1.25/GB/mo, zero egress)
- Optional Cloudflare Stream for adaptive bitrate streaming
- APScheduler running in FastAPI process for campaign scheduling
- Webhook endpoints for Zoom, Pictory, Buffer
- HMAC signature verification on every webhook handler

### Tests + Quality

- ~50 new test cases across CMS, LMS, Zoom, social
- All ~380 existing tests continue to pass
- Backward compat tests for CR-1 through CR-6 (per contract §15)
- Manual scenario testing per §18 of contract before every push

---

## ❌ OUT OF SCOPE (Phase 2 candidates)

These are deferred to Phase 2 with the explicit understanding that they
WILL be needed for SaaS launch but should not be built until validation
passes (see `validation-gates.md`).

Listed here for traceability — items move to `phase-2-backlog.md` when
Phase 2 begins.

### SaaS plumbing (the "TovaiTech-the-product" layer)
- Tenant signup flow at tovaitech.in
- Email verification for new tenants
- Tenant onboarding wizard (workspace setup, integrations connect)
- Multi-tenant routing middleware (resolve tenant from JWT/subdomain/custom domain)
- Subdomain routing (acme.cpmaiexamprep.com or app.tovaitech.in/[tenant])
- Custom domain mapping (per-tenant CNAME + Caddy SSL provisioning)
- Marketing site (tovaitech.in landing, features, pricing, blog)
- Billing — TovaiTech bills tenant via Razorpay/Stripe Connect
- Subscription plan tiers (Starter/Growth/Pro/Enterprise) with feature gates
- Per-tenant AI quota enforcement
- Per-tenant storage quota enforcement
- Per-tenant rate limiting

### Tenant admin UI (each tenant's own settings)
- Workspace settings page (name, slug, logo, theme)
- Payment gateway configuration UI (tenant connects own Razorpay/Stripe)
- Email sender configuration (tenant's domain + DKIM/SPF)
- Team members + roles UI
- API keys management UI
- Webhooks configuration UI
- AI settings UI (BYOK option, model selection, style guide editor)
- Custom domain configuration UI

### Super-admin operator tooling
- Cross-tenant dashboard (MRR, ARR, churn, signups)
- Per-tenant impersonation (with audit log)
- AI cost analytics by tenant
- Suspended/comp tenant management
- Customer support inbox integration

### Advanced AI features (Phase 2 polish)
- Image-to-page (vision-based page generation from screenshot)
- RAG-grounded content generation (per-tenant knowledge base)
- Tab-to-complete inline ghost text in BlockNote
- Page quality score with breakdown
- Auto-suggest related blocks
- Translate page to other languages

### LMS polish
- PDF certificate generation + signing + customisation
- Drip schedule (release one module per week from enrollment)
- Sequential unlocking (Module 2 locks until Module 1 80% complete)
- Live cohort management (batches, roll-overs)
- Discussion forum per lesson
- Assignment uploads + grading
- Mobile app (PWA or native)

### Social automation polish
- Visual workflow builder for tenants (replacing fixed templates)
- Multi-step branching workflows
- A/B testing of content variants
- Cross-platform content adaptation (different post for Twitter vs LinkedIn)
- Native video generation (replacing OpusClip dependency)

### CMS polish
- Page templates library (How-to, Pricing, FAQ, Documentation)
- Versioning + rollback (every save → new version)
- Scheduled publish/unpublish
- Page-level analytics (views, scroll depth, conversion)
- Custom block types (admin-defined React components)
- Markdown import/export

### Anything discovered during Phase 1 that doesn't fit the 6-week budget

If something useful is discovered during build, it gets added to
`phase-2-backlog.md`, NOT shoehorned into Phase 1.

---

## 🎯 Acceptance Criteria — "Phase 1 Done"

Phase 1 is complete when ALL of these are demonstrably true:

### Functional acceptance

- [ ] CPMAI admin can create/edit a Study Guide page via `/admin/content-pages`,
      with drag-drop blocks, no redeploy needed
- [ ] Page updates appear on `/study-guide` within 10 seconds of save
- [ ] Page `nav_visibility` setting actually changes header nav (tested for
      anon, authenticated, subscribed users)
- [ ] CPMAI admin can build a course with chapters and lessons, upload
      videos to R2
- [ ] Subscribed users see "My Courses" with their enrolled courses
- [ ] Video playback works on Chrome desktop, Safari desktop, Chrome mobile,
      Safari iOS
- [ ] Lesson progress saves and shows the right percentage
- [ ] CPMAI admin can schedule a Zoom session via `/admin/sessions`
- [ ] Subscribed users see `/sessions` with upcoming + past sessions
- [ ] Live session join works ONLY from cpmaiexamprep.com (forwarded URLs fail)
- [ ] Admin controls (mute/video/chat) actually constrain participants
- [ ] Recording auto-archives to R2 within 1 hour of session end
- [ ] Recording playback works for subscribed users
- [ ] CPMAI admin can configure a campaign in `/admin/campaigns`
- [ ] Campaign runs at scheduled time, posts appear in Buffer queue
- [ ] AI-generated post text + Pictory video flow through end-to-end

### Backward compatibility acceptance

- [ ] Existing CPMAI users can log in with their stored JWT (no re-login)
- [ ] `/dashboard`, `/exams/*`, `/pricing`, `/admin/*` all work unchanged
- [ ] AssistantWidget chat still works, RAG retrieval unchanged
- [ ] Existing subscription flow (Razorpay + PayPal) unchanged
- [ ] All ~380 existing backend tests pass
- [ ] All ~30 existing frontend tests pass

### Contract compliance acceptance

- [ ] Every new table has `tenant_id` (per contract I-1)
- [ ] `get_current_tenant_id()` is the single source of truth (per I-4)
- [ ] No code path hardcodes `tenant_id=1` outside the stub function
- [ ] Asset storage paths use `tenants/{id}/...` prefix (per S-1)
- [ ] All PRs have §17 + §18 checklists completed
- [ ] Contract document has no open deviations

### Operational acceptance

- [ ] Production smoke test passes after deploy
- [ ] R2 storage configured with backup/lifecycle policies
- [ ] APScheduler health endpoint reports healthy
- [ ] Zoom webhook signature verification works
- [ ] All third-party API keys in `.env` (none committed)

### Documentation acceptance

- [ ] Every new endpoint documented in code (FastAPI OpenAPI auto-gen)
- [ ] Admin UI has tooltips explaining new features
- [ ] `phase-2-backlog.md` updated with anything discovered during build
- [ ] `CHANGELOG.md` updated with Phase 1 release notes

### Stakeholder sign-off

- [ ] Operator (mssoppadla) clicks through 5 manual acceptance scenarios
      end-to-end and signs off

---

## PR sequence summary

Approximate work breakdown across 6 weeks:

| Week | PR | Feature | Migration | Approx LOC |
|---|---|---|---|---|
| 1 | #2 | Multi-tenant foundations (tenants table + tenant.py stubs) | 0023 | ~400 |
| 1–2 | #3 | CMS: content_pages JSONB + BlockNote editor + admin UI | 0024 | ~800 |
| 2 | #4 | CMS: public renderer + Study Guide live + nav integration | none | ~300 |
| 3 | #5 | LMS: courses + chapters + lessons schema + admin builder | 0025 | ~700 |
| 3–4 | #6 | LMS: Plyr video player + R2 upload + student "My Courses" | none | ~600 |
| 4 | #7 | Zoom: sessions schema + Zoom API integration + admin scheduler | 0026 | ~500 |
| 5 | #8 | Zoom: SDK embed + recording webhook + R2 archive + playback | none | ~600 |
| 5–6 | #9 | Social: campaigns schema + APScheduler + workflow runners | 0027 | ~700 |
| 6 | #10 | Social: admin UI + integrations + AI workflows | none | ~600 |
| 6 | #11 | Multi-tenant hygiene + final polish + acceptance verification | none | ~200 |

**Total**: 10 PRs over 6 weeks. ~5,400 LOC across backend + frontend + tests.

Each PR follows the §17 checklist + §18 local testing gates. No PR
ships without manual scenarios documented in its description.
