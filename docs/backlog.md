# Backlog

Working document. Picks up where the last session left off.

Each item is self-contained — you (or future-Claude) can act on it cold
without re-reading the chat history. Edit this file directly from
GitHub mobile when priorities shift.

**Conventions**:
- `[BUG]` — broken in prod, fix when you can
- `[FEATURE]` — net-new functionality
- `[INFRA]` — deploy / CI / observability gap
- `[VERIFY]` — confirm a recent change works on prod
- `[DONE]` — keep around for reference; remove after a sprint

---

## Active bugs

### [BUG] "Talk to a human → Request callback" throws "Failed to fetch"

**Where**: Chat widget → "Talk to a human →" link → fill phone → "Request
callback" button.

**Symptom**: Button click shows the literal string "Failed to fetch" in
the form's error area. No lead row gets created in `/admin/leads`.

**Why this matters**: First high-intent escalation feature shipped — if
it doesn't work, prospects clicking it bounce silently.

**Most likely cause** (educated guess from the code, no prod repro yet):
The `request()` helper in `frontend/src/lib/api.ts` always sets
`credentials: "include"`. That tells the browser to send cookies on
every fetch and triggers a stricter CORS path. If `CORS_ORIGINS` on prod
is `["*"]` instead of an explicit `["https://cpmaiexamprep.com"]`, the
browser rejects credentialed requests with wildcard origin and surfaces
it as `TypeError: Failed to fetch` — not a normal API error code.

Could also be a trailing-slash redirect: `/leads` is registered with
`@router.post("")` (empty path). Depending on FastAPI's
`redirect_slashes` setting, a 307 on the CORS preflight will surface
the same way.

**Cheapest diagnostic** (5 min on prod):
1. Open browser devtools → Network tab
2. Click "Talk to a human → Request callback"
3. Check the failed request — three things to see:
   - Did `OPTIONS /leads` return 200 with `Access-Control-Allow-Origin`
     matching your origin (not `*`)?
   - Did the actual `POST /leads` happen, or was it blocked?
   - If `POST` happened, what's the status code + body?

**Cheap fixes to try, in order**:
1. Drop `credentials: "include"` for the `/leads` call specifically (it's
   anon — doesn't need cookies). One-line change in
   `frontend/src/lib/api.ts:leads.submit`.
2. Make `CORS_ORIGINS` explicit in `backend/.env` on prod if it's
   currently `["*"]`.
3. Change `@router.post("")` → `@router.post("/")` in
   `backend/app/api/v1/endpoints/leads.py` to avoid the empty-path
   ambiguity. Or pass `redirect_slashes=False` to `FastAPI()` init.

**Estimate**: 30 min including local test + prod verify.

---

## Day 3 features (deferred from the 3-day AI rollout)

Original plan committed to four items. Days 1 + 2 shipped; Day 3 didn't
fit the Thursday deadline and was deferred.

### [FEATURE] Human-in-the-loop reply (reactive)

**Ask**: When the AI gives a bad answer, the user can flag the turn. Admin
sees flagged turns in a queue. Admin replies, system emails the user
the follow-up answer.

**Architecture**:
- New column on `AssistantLog`: `flagged_for_review BOOLEAN`,
  `admin_reply TEXT`, `replied_at TIMESTAMP`, `replied_by INTEGER FK
  users(id)`.
- `POST /assistant/chat/turns/{id}/flag` — user-facing, sets flag.
- `GET /admin/chat-history/flagged` — admin queue (filter by
  `flagged_for_review=true AND replied_at IS NULL`).
- `POST /admin/chat-history/turns/{id}/reply` — admin reply, triggers
  email via existing email infrastructure.
- Widget: small "Wasn't helpful" link below each AI turn.

**Reactive only** (per earlier scope decision — no proactive monitoring).
Triggered by user dissatisfaction, not by AI confidence scores.

**Estimate**: ~250 LOC across model + migration + 3 endpoints + email
template + widget UI. ~3-4 hours.

---

### [DONE] GDPR endpoints (data export + delete) — already shipped

Verified 2026-05-21: both the backend (`GET /users/me/export`,
`DELETE /users/me` via `app.services.user_deletion.soft_delete_user`)
and the frontend UI (in `/dashboard` with typed-`DELETE` confirmation
modal) are live. PII redaction follows the documented contract;
financial records retained 7 years per Indian tax law.

Original ask (kept for reference):

**Ask**: EU compliance baseline. User can export their data and delete
their account through self-serve UI.

- `GET /users/me/export` — returns a zip with all user-scoped rows
  (user profile, exam attempts, payments, assistant logs, leads where
  email matches). Use `BackgroundTasks` for large exports → email a
  signed download link, OR return inline for small accounts.
- `DELETE /users/me` — soft-delete with cascade redaction:
  - `users.email` → `deleted-{user_id}@redacted.invalid`
  - `users.name`, `users.password_hash`, `users.google_id` → NULL
  - `users.is_active` → false, `users.deleted_at` → now()
  - Assistant log inputs already PII-redacted at capture; leave them.
  - Payments/subscriptions retained for tax law (typically 7 years).
- Frontend: settings page (or `/users/me/dashboard`) "Download my data"
  and "Delete my account" buttons. Confirmation modal with typed
  "DELETE" string for the destructive action.

**Compliance gotcha**: Don't truly hard-delete payment records —
Indian tax law requires 7-year retention. Redact PII but keep the
financial trail.

**Estimate**: ~200 LOC. ~2-3 hours.

---

### [FEATURE] Rule-based lead scoring

**Ask**: Each lead in `/admin/leads` gets a 0–100 score so the sales
operator can sort by likelihood-to-convert and work top-down.

**Inputs** (all already captured):
- UTM source: `google` +20, `linkedin` +15, direct +10, organic +5
- Plan interest (from `interests` JSON): mentions `premium`/`monthly` +20
- Phone provided: +15
- Notes length: 50-200 chars +10
- Repeat visitor (multiple leads from same email or anon_id): +15
- Page submitted from: `/pricing` +15, `/exams` +10, landing form +5

**Implementation**:
- New column `leads.score INTEGER` (computed at insert time, recomputed
  on edit).
- Service function `calculate_lead_score(lead) -> int` in
  `app/services/lead_scoring.py`. Pure function, easy to unit-test.
- Sortable column added to `/admin/leads` page.
- Tag chips on each row: "HOT" (≥70), "WARM" (40–69), "COLD" (<40).

**Why rule-based, not ML**: At our volume (1 lead in the system today)
ML is overkill. Rules are explainable, easy to tweak when the operator
sees a pattern.

**Estimate**: ~150 LOC. ~1.5 hours.

---

### [FEATURE] Eval framework Tier 2

**Ask**: An auto-generated golden set of (question, expected-intent,
expected-RAG-source) tuples, run via CLI, produces a markdown report.

**Pipeline**:
- `python -m app.eval.generate_golden` — derives Q→intent labels from
  FAQ + question explanations. ~50 questions auto-generated, ~10
  hand-crafted "tricky" cases (cross-domain, ambiguous, banned-topic
  edge cases).
- `python -m app.eval.run` — runs the golden set through
  `IntentClassifier.classify()` and `Retriever.retrieve_top_k(k=4)`.
  Asserts intent matches AND at least one retrieved chunk overlaps the
  expected source.
- Output: `docs/eval-reports/<timestamp>.md` with pass/fail summary +
  failing-case diffs.

**Why now**: Each new handler/setting risks regressing the existing
behavior. Today there's no way to measure that besides manual smoke.

**Estimate**: ~300 LOC + ~50 golden cases. ~3-4 hours.

---

## Infra / DX gaps

### [DONE-WONT-DO] CI: run `alembic upgrade head` from an empty DB

**Status**: explored, structurally incompatible with the codebase, closed
on 2026-05-21.

**Why we tried**: prod outages from model-vs-migration drift that
`Base.metadata.create_all() + alembic stamp head` (used in tests + CI
bootstrap) wouldn't catch.

**Why we can't do it**: `0001_baseline.py` is intentionally a no-op
marker (per `vps-deployment-lessons.md` row #23). The original schema
was built via `Base.metadata.create_all()` then stamped. Running
`alembic upgrade head` from an EMPTY DB fails at
`0003_payment_providers` with `relation "users" does not exist`
because the users table is only created by `create_all()`, not by any
early migration. Restructuring 0001 to actually create the early
schema would be a multi-PR migration refactor with non-trivial risk
to existing prod state.

Round-trip-the-latest-migration (downgrade -1 then upgrade head) is
also not viable: per contract M-2, all our recent migrations
intentionally `raise NotImplementedError` on downgrade to protect
prod data from automated rollbacks.

**What we have instead** (already shipped in `deploy.yml`):
- `alembic check` — model-vs-migration drift detection via autogen
- `alembic upgrade head` on bootstrapped schema — idempotency check
- The `transaction_per_migration=True` invariant pinned by
  `test_alembic_env_config.py`

Together these catch the drift class the backlog item worried about.
The empty-DB gate stays a "known limitation" of the architecture.

### [INFRA] One-time VPS image cleanup

**Why**: `deploy.sh` auto-prunes dangling images older than 7 days at
the end of every successful deploy. But today's two failed deploys
never reached the prune step, so the disk has accumulated more layers
than usual.

**Command** to run once on the VPS (read-only check + cleanup):

```bash
docker system df -v          # see current usage
docker image prune -af        # remove unused (running images stay)
docker builder prune -af      # reclaim build cache mounts
```

`cpmai-prep-backend:previous` and `cpmai-prep-frontend:previous` tags
will survive — those are the auto-rollback targets. Future deploys
keep disk clean automatically.

**Estimate**: 5 min.

---

## Post-merge verification (sanity-check the recent deploys)

Items merged today that haven't been hand-verified on prod yet.

- [ ] Share landing URL from mobile (iOS Safari + Android Chrome) →
      confirm `cpmaiexamprep.com`, not the old `cpmai-prep.example`
      placeholder. (PR #22)
- [ ] FAQ accordion on `/` → first item open, rest collapsed; tapping
      any toggles. (PR #22)
- [ ] Chat widget appears on `/`, `/pricing`, `/dashboard`, `/exams`
      when signed in; nothing for anon visitors. (PR #21)
- [ ] On a mobile device, chat bubble sits above the iOS home indicator
      / Android gesture bar; doesn't shift when the address bar
      appears/disappears. (PR #21)
- [ ] Edit `assistant.widget_subtitle` in `/admin/settings`, refresh
      `/exams`, confirm the new subtitle shows under "CPMAI Assistant"
      in the chat panel header. (PR #20)
- [ ] In `/admin/users`, click "Set chat limit" on a test user, enter
      5, log in as that user, send 6 chat messages → 6th gets 429.
      (PR #20)
- [ ] Configure an Anthropic provider in `/admin/llm-providers` with a
      real `sk-ant-...` key, activate, send a chat message, confirm
      reply uses Claude (compare style to OpenAI replies). (PR #19)

---

## Future product (no commitment yet)

### [FEATURE] International pricing — USD column + currency selector

**Ask** (two halves that go together):
1. **Pricing page** should show an **additional USD column** alongside
   the INR price. Same plans, two amounts side-by-side. Visitors outside
   India self-identify with the USD column; visitors in India see INR
   as the primary.
2. **User chooses payment currency** on checkout. Selection drives which
   payment provider opens:
   - INR → existing Razorpay India flow (UPI, NetBanking, India cards)
   - USD → Razorpay's international / PayPal handoff (for cards billed
     in USD by issuers outside India)

**Why this matters**: The GeoIP work (PR-A) now populates
`users.country` at signup. With that field already in place, the UI can
default the currency selector intelligently:
- `country IN` → INR pre-selected
- `country ∈ {US, GB, AE, SG, CA, AU, …}` → USD pre-selected
- Anything else → show both with no default
Without GeoIP, this same feature would have needed an explicit "where
are you?" prompt. PR-A makes it a one-line conditional.

**Architecture sketch**:

* **Plans model** (`backend/app/models/plan.py`):
  add `price_usd_cents INTEGER NULL`. Nullable so existing plans don't
  break — admin fills in via the plans page. Discount + offer logic
  needs the same dual-column treatment (`discount_price_usd_cents`).
* **Admin /admin/plans page**: dual price inputs side-by-side; the
  pricing-page render auto-shows both columns when at least one plan has
  a USD price set.
* **Pricing-page** (`/pricing`): two columns under each plan card.
  Currency-symbol prefix per column (₹ / $). Optionally a subtle
  "Prices in your currency: USD" pill above the grid based on GeoIP.
* **Pricing API** (`/api/v1/pricing/quote`): accept a `currency=INR|USD`
  query param; default from the authed user's `country` (or anon
  `X-Forwarded-For` lookup). Return `amount_cents` + `currency` in the
  response. `pricing.gst_percent` only applies to INR (GST is an
  India-specific tax).
* **Payment provider routing**: extend the `payment.active_provider_id`
  pattern to a tuple — `payment.inr_provider_id` and
  `payment.usd_provider_id`. The /payments/create-order endpoint reads
  the currency from the request, picks the matching provider config,
  and uses its credentials. The frontend's checkout button bootstraps
  Razorpay-INR or Razorpay-international/PayPal accordingly. (Razorpay
  has a separate "international" key set for USD acceptance — admin
  configures both in /admin/payment-providers.)
* **Reconciliation**: webhooks differ — Razorpay-INR sends a different
  signature header from Razorpay-International. The existing webhook
  router can dispatch based on a `payment_provider_id` claim on the
  order metadata.

**Compliance + tax notes**:
- GST is INR-only. The `pricing.gst_percent` setting must NOT be
  applied to USD prices. Validate in the pricing-quote endpoint.
- USD payments may have higher FX + processor fees. Set USD prices to
  cover the gap; don't compute USD from INR at request time (FX rates
  drift, prices look weird).
- For India tax filings, USD-billed customers still need a receipt
  with their country printed — the GeoIP `country` field plumbs through.

**Frontend defaults using GeoIP** (the bit that ties this to PR-A):
- Logged-in users: `user.country` decides the default currency.
- Anonymous visitors: `extract_client_ip(request)` → geoip lookup at
  page render time (server component). Same fail-open contract: if
  GeoIP misses, no pre-selection, user picks manually.

**Tradeoffs**:
- Two prices to maintain. Admin needs to keep USD price aligned with
  INR price after FX moves; can build a "suggest USD from INR at
  today's FX" helper if it becomes painful.
- Two payment provider configs to keep working. If the
  international Razorpay account ever goes inactive, USD checkout silently
  breaks — needs the same `test connection` button we built for GeoIP.
- Customer support: refund flows have to know which provider issued
  the original charge. The webhook dispatcher already keys on
  `payment_provider_id` in our metadata, so this works as long as
  refund flow honours that field.

**Open questions** (decide before coding):
- Which payment processor for USD? Razorpay International is the
  obvious choice (single backoffice for both currencies). PayPal is a
  separate integration with its own webhook shape — meaningful work.
  Default plan: Razorpay International first, defer PayPal unless a
  customer specifically asks.
- Pin USD prices in cents (e.g. $99.00 = `9900`) OR allow a float?
  Strongly prefer cents — same model as INR `price_paise`. No floats.
- Should the user be able to OVERRIDE the GeoIP-based default
  (e.g. an Indian using a US card)? Yes — the dropdown is always
  visible; GeoIP just picks the initial value.

**Estimate**: ~500 LOC backend + ~200 LOC frontend + ~5 unit tests
+ 1 migration. ~1.5 days. Could split as:
- Phase 1: USD column + manual currency selector (no provider routing
  — both currencies still use INR razorpay; nothing actually charges
  USD). Ships value via the "Indians see INR, foreigners see USD"
  display alone. ~0.5 day.
- Phase 2: International payment provider + webhook routing. ~1 day.
- Phase 3: GeoIP-driven default + currency-aware GST. ~0.5 day.


### [FEATURE] Anonymous chat widget on marketing pages

**Ask**: Show the chat to anon visitors on landing/pricing so prospects
can try the AI before signing up.

**Architecture sketch**:
- Anon quota separate from user quota — `chat.daily_limit.anonymous`
  setting (default 3 messages/day per IP+anon_id).
- Drop the `if (!user) return null` guard in `AssistantWidget`.
- Backend `/assistant/chat` already has an `X-Anon-Token` path for
  exams — extend it here.
- After anon quota hits zero, the widget panel shows an "Sign up for
  unlimited" CTA pointing to `/login?intent=signup`.

**Tradeoffs**: More OpenAI spend. Bot abuse vector (rate limit by IP
helps but isn't bulletproof). Could increase lead conversion or could
become noise.

**Open question**: Want this at all, or keep the AI as a signed-in-only
benefit? Defer until we have data on lead-form conversion.

**Estimate**: ~150 LOC. ~2 hours.

---

## Done (recent — remove after a sprint)

- 2026-05-11: AI Day 1 + Day 2 — RAG, chat widget, guardrails, admin
  RAG uploads, admin chat history, per-user chat-limit, Anthropic
  provider, configurable strings, callback form, mobile polish, FAQ
  accordion, share-URL fix, deploy auto-rollback. (PRs #13–#22)
