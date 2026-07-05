# Email Automation Contract

**Status**: v1 — locked 2026-07-05
**Owners**: mssoppadla
**Related**: `docs/contracts/multi-tenancy-and-saas-integration.md` (I-1..I-n apply),
`backend/app/services/email/mailer.py` (existing lead auto-offer flow — untouched)

## 0. Purpose

Admin-extensible lifecycle email automation: admins create **mail types**
("automations") — WHEN `<trigger>` IF `<conditions>` WAIT `<delay>` SEND
`<personalized content + attachments>` — with zero code changes per new
mail type. Ships pre-seeded with four automations:

| Seed | Trigger | Default delay | Default policy |
|------|---------|--------------|----------------|
| Welcome — signup without payment | `user.signup` + condition `has_active_subscription=false` | 20 min | once_per_user |
| Payment received | `payment.success` | 0 min | every_event |
| Exam follow-up | `exam.submitted` | 2880 min (2 days) | replace_pending |
| Payment failed — need help? | `payment.failed` | 30 min | every_event + 1-day cooldown |

All seeds ship `is_active=false`; nothing sends until the admin reviews
content, configures SMTP, and flips both the per-automation toggle and
the master switch.

## 1. Scope

### In scope
- New tables `email_automations`, `email_outbox` (migration 0038)
- Trigger hooks in auth signup, payment lifecycle, exam submit paths
- Outbox dispatcher job on the shared APScheduler + abandoned-payment sweeper
- Attachment support in `mailer.send_email`
- Admin API + UI: `/admin/email-automations` (Email Account / Mail Types /
  Activity tabs), bulk manual send from `/admin/users`, `/admin/payments`
- New runtime setting `email.lifecycle_enabled` (master kill switch)

### Out of scope / untouched
- The existing lead → auto-offer flow (`email_templates` table, its admin
  page, `send_lead_offer_email`) keeps working unchanged. Lifecycle mail
  types live in their own table — they are NEVER selectable by
  `select_template()` and can't shadow the lead default template.
- No new containers, queues, or deploy-script changes.
- Marketing-consent semantics for leads (lifecycle mail goes to *account
  holders* about their own account/purchase/exam — transactional footing).

## 2. Data model (invariants)

### I-1 compliance
Both new tables carry `tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES
tenants(id) ON DELETE CASCADE`, indexed as the leading column of the hot
query path indexes.

### `email_automations` — one row per admin-defined mail type
- `trigger_key` — MUST be one of the code catalog (§3). Validated at API
  boundary; an unknown key in DB is skipped at dispatch with a WARN log.
- `conditions` JSON — list of `{type, ...params}` predicates (§4).
  Evaluated **at enqueue time AND re-evaluated at send time**; send-time
  failure → outbox row status `skipped` with reason.
- `delay_minutes` int ≥ 0 (UI presents days/hours/minutes).
- `subject` (≤240), `html_body` (Text) — `{{placeholder}}` substitution
  via the existing `render_template` (unknown placeholders stay verbatim).
- `attachments` JSON — list of `{url, filename, mime_type, size_bytes}`
  as returned by `/admin/uploads`. Total size ≤ 15 MB enforced at save.
  URLs MUST resolve under `UPLOAD_ROOT` (path-traversal guard at send).
- `send_policy` — `once_per_user | replace_pending | every_event`.
- `cooldown_days` int ≥ 0 — only meaningful for `every_event`; suppresses
  a new send if one was SENT within the window.
- `is_active` bool — per-mail-type admin toggle (R6).

### `email_outbox` — durable queue AND send history (R7)
- `automation_id` FK (SET NULL on automation delete — history survives),
  `user_id` FK, `to_email`, `scheduled_at`, `status`
  (`pending | sent | skipped | failed | cancelled`), `attempts`,
  `last_error` (failures), `skip_reason` (skips), `sent_at`,
  `context` JSON (rendered-placeholder snapshot for admin debugging),
  `source` (`automation | manual`) — manual = bulk send from Users page.
- `dedup_key` VARCHAR unique, format `{automation_id}:{user_id}:{ref}`:
  - `once_per_user` → ref = `"once"` (one row ever per user+automation)
  - `replace_pending` → ref = `"latest"`; a new event UPDATES the
    pending row's `scheduled_at`/`context` instead of inserting
  - `every_event` → ref = event id (payment id / exam session id / ULID)
- Retry: a `failed` send is retried by the dispatcher up to 3 attempts
  with the tick interval as spacing, then left `failed` (visible in
  Activity; admin can requeue).

## 3. Trigger catalog (code-defined; additive-only)

| Key | Hook location | Extra placeholders |
|-----|--------------|--------------------|
| `user.signup` | `AuthService.signup` + Google provisioner `created` path | `signup_method` |
| `user.login` | `AuthService.login` + Google returning path | `signup_method` |
| `payment.success` | `activate_subscription_for_payment` | `plan_name`, `amount`, `currency`, `expires_at` |
| `payment.failed` | `mark_payment_failed` | `plan_name`, `amount`, `currency`, `provider` |
| `payment.abandoned` | sweeper: Payment `status='created'` older than N hours (automation's delay field = N·60) | `plan_name`, `amount`, `currency`, `hours_since` |
| `exam.submitted` | `ExamService.submit` (only when `user_id` is not NULL) | `exam_title`, `score`, `passed`, `attempt_date` |

Shared placeholders on every trigger: `name`, `email`, `brand_name`,
`enroll_url`, `offer_code`, `offer_valid_until` (same resolution as the
existing `build_ctx`). The catalog (keys, labels, placeholder lists) is
served by `GET /admin/email-automations/catalog` — the frontend never
hardcodes it.

Hook contract: enqueue is **fail-soft** — an enqueue error must NEVER
break signup/login/payment/exam requests (log + swallow, same discipline
as `emit_event`). `payment.success` additionally cancels any `pending`
outbox rows for the same user whose automation trigger is `user.signup`
or `user.login` (the "they paid before the nudge fired" rule) and whose
conditions include unpaid-status.

## 4. Condition types (code-defined; additive-only)

| type | params | semantics |
|------|--------|-----------|
| `has_active_subscription` | `value: bool` | active sub = `status='active'` AND (`expires_at` NULL or future) |
| `signup_method` | `value: google\|password` | `google_id` set / password_hash set |
| `exam_set_submitted` | `exam_set_id, value: bool` | user has (not) a `submitted` ExamSession for that set |
| `days_since_signup` | `op: lt\|gt, days` | vs `User.created_at` |

Unknown condition type in DB → automation is skipped at dispatch with a
WARN (defensive; API validates on write).

## 5. Dispatcher

- Interval job (60 s) registered on the SHARED AsyncIOScheduler in
  `app/main.py` startup, same pattern as the visitor-insights rollup.
  Skipped when `APP_ENV=test` (tests call the tick function directly).
- Tick: claim due `pending` rows (`scheduled_at <= now`, batch cap 50),
  for each: master switch on? automation exists + `is_active`? conditions
  still hold? cooldown ok? → render + send → `sent` (+`sent_at`) else
  `skipped`/`failed` (+reason/error). Every transition audit-logged.
- Single uvicorn process (current prod topology) → no cross-process
  claim race. If workers ever scale out, add `FOR UPDATE SKIP LOCKED`
  claiming — noted here so the gap is explicit.

## 6. Email account setup (R8)

Reuses the existing runtime-settings keys (`email.smtp_*`,
`email.from_*`) — no new storage, same secret masking for
`email.smtp_password`. New endpoint
`POST /admin/email-automations/test-send` performs a REAL SMTP
connect+send to the requesting admin (or override recipient) and returns
the actual failure string (auth/connection/TLS) instead of fail-soft
swallowing. The page ships an inline Hostinger setup guide (create
mailbox → enter creds → check SPF/DKIM → test) and a config-completeness
banner. Master switch cannot be enabled while required keys are missing.

## 7. Bulk manual send (R9)

`POST /admin/email-automations/{id}/bulk-send` with `{user_ids: [...]}`
(≤500 per call): one outbox row per user, `source='manual'`,
`scheduled_at=now`, dedup key `manual:{automation_id}:{user_id}:{ulid}`.
Conditions and the per-type ``is_active`` toggle are NOT applied to
manual sends (the admin explicitly chose the template and recipients —
a mail type may be kept disabled precisely because it is manual-only);
personalization always applies, and the ``email.lifecycle_enabled``
master switch still gates dispatch. Users page gains paid/unpaid +
signup-method filters and row checkboxes.

## 8. Payments visibility (R10)

`GET /admin/payments` — paginated, filters: status
(`captured|failed|created|refunded`), `abandoned_hours` (status=created
older than N hours), plus user email/plan columns. Read-only in v1.
Sweeper job (15-min interval, same scheduler) finds abandoned payments
and enqueues `payment.abandoned` automations (dedup ref = payment id —
one nudge per abandoned order per automation).

## 9. Security & privacy

- All new admin endpoints behind `get_admin_user`; audit_log on every
  mutation and every send/skip/fail.
- Attachment paths resolved strictly under `UPLOAD_ROOT` (reject `..`,
  absolute paths, symlink escape via `Path.resolve().is_relative_to`).
- Outbox `context` snapshot stores rendered values (name, plan, score) —
  same PII class as audit_log; admin-only surface.
- SMTP failures logged WITHOUT credentials.

## 10. Testing gates (all must pass before any push — R12)

1. Unit: render/personalization, condition evaluator, dedup-key builder,
   attachment path guard, cooldown logic.
2. Integration: each trigger enqueues; pay-during-wait cancels signup
   nudge; dispatcher tick sends/skips/fails + statuses/dates recorded;
   admin CRUD + validation (unknown trigger/condition rejected, >15 MB
   attachments rejected); bulk send; payments listing + abandoned filter;
   catalog endpoint; settings drift guard updated for
   `email.lifecycle_enabled`.
3. `alembic upgrade head` AND `downgrade -1` verified on a fresh
   python:3.12 docker run (local Python 3.14 lacks wheels — see
   project_local_test_run memory).
4. Full backend suite + frontend `npm run build` + tests: ZERO failures
   including pre-existing.
5. Single push to GitHub only after 1–4 pass.

## 11. Non-goals (v1)

- Open/click tracking, unsubscribe-list management, per-user opt-out
  flags, HTML drag-drop email builder, cross-process outbox claiming,
  R2/S3 attachment storage. All additive later without schema breakage
  (outbox and automations tables already carry the needed keys).
