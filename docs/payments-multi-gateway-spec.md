# Multi-Gateway Payments — Specification & Contracts

Status: **awaiting operator approval** · Author: 2026-08-16 session
Scope source: operator requirements (multi-gateway routing, admin
listing control, fraud handling, dispute evidence, compliance
dashboard) refined across 2026-08-15/16 discussions.

Guiding constraints (operator-mandated):
1. **Existing flow untouched until proven** — every new behavior is
   dormant behind settings whose defaults reproduce today's behavior
   exactly. Rollback at every step is a runtime-settings flip (~30s,
   no deploy).
2. **All existing user data intact** — no schema or row changes to any
   guarded table; the deploy data-preservation guard independently
   enforces this on every deploy.
3. Contracts → breakage check → tests written first → implement →
   validate the same tests against production post-deploy.

---

## 1. Requirement summary (approved scope)

| # | Feature | Phase |
|---|---------|-------|
| R1 | Gateway **listing control**: per provider entry, admin controls Enabled (can service past payments) / **Listed** (sellable, per INR / non-INR scope) / priority order | 1 |
| R2 | **Display mode** for international checkout: `auto` (customer sees only top-priority listed gateway — today's UX) or `choice` (2+ listed → customer picks). Suspension response = unlist entry, customers instantly see only active gateways | 1 |
| R3 | INR **cutover lever**: INR routing between Personal/Company Razorpay entries. Default 100% Personal. Simultaneous %-split machinery present but parked pending CA sign-off (cross-entity GST/invoicing) | 1 |
| R4 | **Kill switch** `payments.intl_enabled`: instantly stop non-INR order creation; intl-notice banner is the customer-facing companion message | 1 |
| R5 | **Fallback**: order-creation-time failure on the primary listed gateway retries the next listed one. No mid-payment/decline fallback (declines are the customer's bank, not the gateway) | 1 |
| R6 | **Webhook multi-account hardening**: callbacks verified against the specific entry that minted the order, incl. two Razorpay accounts live at once | 1 |
| R7 | **Fraud controls**: order-creation velocity guard (per IP + per user), card-testing tripwire (threshold alert into the error-log dashboard; auto-trip of R4 deferred until thresholds tuned), country allow-list for non-INR | 2 |
| R8 | **Dispute Evidence Pack**: one click per payment on Admin → Payments → single print-friendly report: receipt, customer identity, subscription activation, full usage timeline (exams, lessons, sessions, IPs, devices), policy links | 3 |
| R9 | **Compliance dashboard** (Admin → Compliance): track FIRC records per foreign settlement and gateway document-requests (Razorpay/Stripe queries) as work items — status, due dates, notes, file attachments (existing upload mechanism), due-soon summary | 3 |
| R10 | **Stripe provider**: real integration only when a Stripe account exists; Phase 1 slots make it plug-in (provider class + config entry, appears in listing control automatically) | 4 (deferred) |

Out of scope (explicit): simultaneous cross-entity %-split activation
(CA), billing-address collection, mid-payment fallback, PayPal revival.

---

## 2. Contracts

### 2.1 Database (all additive; NO guarded table touched)

**`payment_provider_configs`** — 3 new nullable/defaulted columns
(migration `0047_gateway_listing`, additive):
| column | type | default | meaning |
|---|---|---|---|
| `listed_for_inr` | bool | false | sellable on the INR rail |
| `listed_for_intl` | bool | false | sellable on the non-INR rail |
| `intl_rank` | int | 100 | ordering among listed intl entries; lowest = preferred |

Backfill in the same migration (idempotent UPDATEs, no deletes): the
entry currently referenced by `payment.active_provider_id` →
`listed_for_inr=true`; the entry referenced by
`payment.non_inr_provider_id` → `listed_for_intl=true, intl_rank=10`.
Result: post-migration behavior is byte-identical to today.

**`payments`** — 1 new nullable column: `provider_config_id`
(FK → payment_provider_configs, nullable). Populated for NEW payments;
historical rows stay NULL and keep resolving via `provider_name`
(existing behavior). Needed so refunds/webhooks distinguish Personal-
Razorpay payments from Company-Razorpay payments. `payments` IS a
guarded table for ROW COUNT — an additive nullable column changes no
rows and passes the guard; rehearsed via `rehearse_deploy.sh` before
push (mandatory).

**`compliance_items`** — new table (not guarded):
`id, kind ('firc'|'gateway_query'|'other'), provider_config_id FK NULL,
title (≤200), reference_no (≤100, NULL), status
('open'|'submitted'|'resolved'), due_at NULL, resolved_at NULL,
notes TEXT NULL, attachment_urls JSON (list of /uploads paths),
created_by FK users NULL, created_at, updated_at` + indexes on
(status, due_at), kind.

### 2.2 Runtime settings (seeded idempotently; defaults = today)

| key | validator | default | effect |
|---|---|---|---|
| `payments.intl_enabled` | bool | **true** | false → non-INR order creation returns 503 w/ admin-hint message |
| `payments.intl_display_mode` | choice(auto, choice) | **auto** | governs R2 |
| `payments.fallback_enabled` | bool | **false** | governs R5 |
| `payments.intl_country_allowlist` | str-list (ISO-3166 alpha-2), empty = allow all | **[]** | R7 |
| `payments.velocity_max_orders_per_10min_ip` | int 1–100 | **15** | R7 |
| `payments.velocity_max_orders_per_10min_user` | int 1–100 | **10** | R7 |
| `payments.tripwire_failed_orders_per_10min` | int 5–500 | **30** | R7 alert threshold |

Existing `payment.active_provider_id` / `payment.non_inr_provider_id`
remain authoritative for the *preferred* entry on each rail (backward
compatible); listing flags define the *choice set* around them.

### 2.3 API

| Endpoint | Method | Auth | Contract |
|---|---|---|---|
| `/payments/gateway-options?currency=USD` | GET | public, rate-limited | `{mode:"auto"|"choice", options:[{provider_config_id:int, provider_type:"razorpay"|"stripe", label:str}]}` — options already filtered by listing, kill switch, allow-list; ordered by rank. `auto` → exactly ≤1 option |
| `/payments/orders` | POST | authed (existing) | body gains OPTIONAL `provider_config_id:int`. Server validates it against the listed set for the order currency; absent → server picks (today's behavior). Invalid/unlisted → 422. Response `CreateOrderOut` unchanged (existing `provider` field keeps telling the frontend which SDK) |
| `/admin/payment-providers/{id}/listing` | PATCH | admin | `{listed_for_inr?, listed_for_intl?, intl_rank?}` → updated provider row. Guard: cannot unlist the last INR-listed entry |
| `/admin/payments/{payment_id}/evidence` | GET | admin | print-friendly HTML document (Content-Type text/html); 404 for unknown payment |
| `/admin/compliance` | GET | admin | `?kind=&status=&limit=&offset=` → `{total, rows:[item]}` |
| `/admin/compliance` | POST | admin | create item (kind, title required) |
| `/admin/compliance/{id}` | PATCH | admin | update status/notes/due_at/reference_no/attachment_urls; `resolved` sets resolved_at |
| `/admin/compliance/summary` | GET | admin | `{open:int, due_7d:int, by_kind:{...}}` — powers dashboard card |

Webhooks: existing paths unchanged; resolution order = match by
`provider_config_id` on the referenced order → fall back to current
single-config behavior for historical payments.

### 2.4 UI

| Surface | Change |
|---|---|
| `/pricing` checkout | `choice` mode only: radio/toggle of listed gateways above Pay (1 listed → nothing new renders). `auto` mode: pixel-identical to today |
| Admin → Payment Providers | per-entry: Listed-INR / Listed-Intl toggles + rank input; existing Activate buttons unchanged |
| Admin → Payments | new per-row "Evidence" action (opens the report in a new tab) |
| Admin → Compliance (new page, sidebar under System) | summary cards (open / due-soon), filterable table, create/edit drawer, file attach via existing uploader |
| Admin → Error Logs | tripwire alerts appear as source `fraud` rows (no UI change needed) |

---

## 3. Breakage verification (existing functionality & data)

| Area | Verdict | Why |
|---|---|---|
| Existing INR checkout (all current customers) | **UNCHANGED** | defaults reproduce today's routing; `auto` mode renders zero new UI; existing `payment.active_provider_id` path untouched |
| Existing subscriptions / course / exam access | **UNTOUCHED** | no entitlement code in scope |
| Historical payments & refunds | **SAFE** | `provider_config_id` NULL on old rows; resolution falls back to existing `provider_name` logic |
| Guarded tables | **ZERO row changes** | only additive nullable column on `payments`; guard verifies `+0` on deploy; `rehearse_deploy.sh` run before push |
| Existing tests | must stay 100% green | any existing test needing edits = contract violation → redesign, not test-editing (exception: none anticipated) |
| Existing webhooks in flight during cutover | **SAFE** | old entries stay Enabled; verification per-entry |
| CreateOrderOut consumers | **COMPATIBLE** | response shape unchanged; new request field optional |

---

## 4. Test catalog (written BEFORE implementation; each maps to a post-deploy check)

### Backend (pytest)
- **T1** gateway-options: auto→single preferred; choice→listed by rank; kill switch off → empty options + orders 503; allow-list filters by GeoIP country; INR options unaffected by intl settings
- **T2** order creation: optional provider_config_id honored when listed; unlisted/disabled id → 422; absent → server pick identical to today (regression pin)
- **T3** fallback: primary mint failure + fallback_enabled → order minted on next listed entry; fallback_disabled → error surfaces unchanged
- **T4** listing PATCH: toggles + rank persist; last-INR-entry guard refuses; admin-gated (401/403 for non-admin)
- **T5** webhooks: two enabled Razorpay entries with different secrets — callback for an order minted on entry B verifies with B's secret and fails with A's; historical (NULL config) payment still verifies via legacy path
- **T6** payments rows: new payment records provider_config_id; old rows unaffected (NULL) and refund path still resolves
- **T7** velocity guard: >N orders/10min per IP → 429; per-user cap independent; under-threshold unaffected
- **T8** tripwire: failed-order burst past threshold → one error_logs row (source "fraud"), no duplicates within window
- **T9** evidence pack: contains payment id/amount/currency, user email, subscription activation, ≥1 exam-attempt timestamp and lesson-progress line when they exist; admin-gated; 404 unknown id
- **T10** compliance CRUD: create/list/filter/patch; resolved sets resolved_at; summary counts open/due-7d correctly; admin-gated
- **T11** settings: all new keys registered + validated (allowlist meta-test rows); invalid values 422
- **T12** migration 0047: rehearse_deploy.sh green (guard flat, downgrade/upgrade replayable)

### Frontend (vitest)
- **T13** choice-mode selector renders only with 2+ options; picks flow into order call; auto mode renders nothing new (snapshot of today preserved)
- **T14** provider listing admin controls render + call PATCH
- **T15** compliance page renders rows/summary; evidence button present per payment row
- **T16** full existing suite stays green untouched

### Post-deploy validation (prod, mirrors the above)
- **V1** `curl /payments/gateway-options?currency=USD` → mode auto, ≤1 option (T1)
- **V2** INR test checkout unchanged (existing smoke already covers) (T2)
- **V3** flip kill switch off in admin → options empty within 30s → flip back (T1/R4)
- **V4** admin listing toggles visible; rank edit persists (T4/T14)
- **V5** evidence report opens for a real past payment and contains usage lines (T9)
- **V6** compliance page: create one FIRC item, attach a file, resolve it (T10/T15)
- **V7** error-log dashboard shows a synthetic fraud row (staging-style check, threshold temporarily lowered then restored) (T8)
- **V8** deploy log: guard all `+0`, marker written, smoke green (T12)

---

## 5. Rollout / rollback / decommission

1. Phase 1 deploys **dormant** (defaults = today). V1–V4 run same day.
2. When Company-Razorpay KYC lands: add entry → list for intl → one
   real foreign-card transaction → open. Rollback at any moment =
   unlist / kill switch (settings only).
3. Phases 2–3 each: own PR, own tests, own post-deploy checks.
4. Confidence period (~2 weeks clean settlements) → decommission:
   delist PayPal entry (stays Enabled for history), optional INR
   cutover via lever (CA approval prerequisite).
