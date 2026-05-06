# End-to-end test plan

Run this whole list after every meaningful change. It's the canonical
checklist of what must work. Most of the API surface is automated by
`scripts/smoke_admin_crud.py`; the parts that need a real browser
(Google sign-in, drag-to-highlight, etc.) are documented below as
manual steps with explicit pass criteria.

## Quick run

```bash
# Automated — covers all the API-side scenarios in 27 checks
python scripts/smoke_admin_crud.py
# expect: "OK — all admin CRUD flows green."

# Then walk the manual scenarios below in a fresh incognito window.
```

If the automated run fails, **stop and fix before touching the manual
checklist** — the manual scenarios assume the API surface is healthy.

---

## What's automated (27 checks in `scripts/smoke_admin_crud.py`)

| # | Section | Step |
|---|---|---|
| 1 | Health | backend `/health` returns 200 |
| 2 | Auth | login as super-admin (password) |
| 3 | Auth | `/auth/google` rejects bogus token (401 configured / 503 disabled) |
| 4 | Question CRUD | create |
| 5 | Question CRUD | update with options replace (the old PATCH-bug regression check) |
| 6 | Question CRUD | get by id |
| 7 | Exam-set CRUD | create |
| 8 | Exam-set CRUD | update (rename + change time limit) |
| 9 | Linkage | link question to set |
| 10 | Linkage | list linked (with full options revealed for admin) |
| 11 | Linkage | reorder |
| 12 | Linkage | unlink |
| 13 | Public | exam set visible to anonymous on `/exam-sets` |
| 14 | Landing | `/content/landing` returns heading + cta + upsell |
| 15 | Landing | PATCH `landing.lead_section_heading` succeeds |
| 16 | Landing | **public endpoint reflects new heading without restart** |
| 17 | Landing | revert heading |
| 18 | FAQ | create |
| 19 | FAQ | update (set inactive) |
| 20 | FAQ | inactive FAQ hidden from public `/content/faqs` |
| 21 | FAQ | delete |
| 22 | Contacts | create junk lead |
| 23 | Contacts | super-admin deletes lead |
| 24 | Premium gate | premium set returns 402 `subscription_required` for un-subscribed user |
| 25 | Free start | free set startable for authed user (201) |
| 26 | Cleanup | delete exam set |
| 27 | Cleanup | delete question |

Run this anywhere with `python scripts/smoke_admin_crud.py`.

---

## Manual scenarios (browser-only)

These need a real browser because they exercise Google's iframe-based
sign-in and selection-based annotations that JS can't fully simulate.
Run each in an **incognito window** so a stale token from the previous
session doesn't mask anything.

---

### Scenario A — New user via Google → free mock exam → score

**Pre-conditions**: Google account that hasn't signed up before
(or run the cleanup in scenario E first to free yours up).

| # | Step | Pass criterion |
|---|---|---|
| A1 | Open `http://localhost:3000/` in incognito | Landing page shows; top-right has the **Sign in with Google** button |
| A2 | Click "Sign in with Google" → pick a Google account | After consent, redirected to `/dashboard` |
| A3 | Verify dashboard | "Welcome, &lt;your name&gt;" + **"Free plan"** badge + "Signed in with Google" tag + grid of free + locked premium sets |
| A4 | Click any **free** set card | Lands on `/exams/<slug>` with the question + Toolbox + ⏱ countdown |
| A5 | Click the **🖍 Highlight** button (toolbox lights up indigo) | Cursor turns to crosshair when over text |
| A6 | Drag-select a few words inside the **question stem** | Just the dragged range gets a yellow highlight; surrounding text stays plain |
| A7 | Click **🖍 Highlight** again to deactivate, then **S̶ Strike** | Strike button now lit |
| A8 | Drag-select a few words inside an **option text** | Just the dragged range gets a line-through |
| A9 | Click **🧽 Eraser**, drag over the highlighted/struck text | Annotation cleared |
| A10 | Pick an answer, then tick **Mark for review** | Question palette shows the row in amber |
| A11 | Navigate to next question | **Tool resets to none** — no tool button is lit anymore |
| A12 | Mark 1-2 more questions for review with different answers (or unanswered) | Palette amber accumulates |
| A13 | Click **Review marked (N)** in the navigation row | Review screen replaces the question UI |
| A14 | Verify the review screen | H1 "Review marked questions" + N items listed (each with stem + answered/unanswered + jump link) + "End review" + "Submit attempt" |
| A15 | Click any marked item | Jumps back to that question, palette ring on the right index |
| A16 | Return to review (top utility row → or last-question button), click **Submit attempt** | Lands on `/exams/results/<id>` |
| A17 | Verify result page | Score % + correct/incorrect/unanswered counts + per-question reveal with each option's correctness flag + reasoning + the user's selected letter |
| A18 | (Quick re-check) Open `tail -f backend/logs/app.jsonl \| grep '"event_name":"exam'` in another terminal | After A17 you should see `exam.started` and `exam.submitted` journey events |

**Expected outcomes**:
- New user row created in `users` with `google_id` set, `password_hash` NULL, `role='user'`.
- Per-attempt annotations stored in `localStorage` per attempt id, wiped on submit.
- All 6 journey events recorded for this session (`auth.signup.google`, `auth.login.google`, `exam.started`, `exam.submitted` — the others are from page views).

---

### Scenario B — Existing user via Google → subscription paths

Run after Scenario A so your Google account already exists.

| # | Step | Pass criterion |
|---|---|---|
| B1 | New incognito window → `/` | Top-right shows Google sign-in (not signed in) |
| B2 | Click "Sign in with Google" → pick the same account as Scenario A | Lands on `/dashboard`, NOT a "Welcome &lt;new name&gt;" — i.e. existing row reused |
| B3 | Click a **premium** exam set card (locked badge) | Lands on `/exams/<slug>` |
| B4 | Verify the paywall page | H1 "**This is a premium exam set**" + **View plans & subscribe** + "Sign in with another account" + "Pick a free set" + "All exam sets" + "Home / FAQs" |
| B5 | Click **Pick a free set** | Returns to `/exams` with the inline banner gone (you're signed in) |
| B6 | Click "My dashboard →" in the top utility row | Lands on `/dashboard` |
| B7 | Click **Home / FAQs** | Lands on `/#faq-heading` with the FAQ section in view |
| B8 | Click "Continue →" in the top bar | Returns to `/dashboard` |
| B9 | Click **Sign out** | Top bar reverts to "Sign in with Google" |

**Expected outcomes**:
- No new user row was created (verify via `/admin/users` row count).
- Subscription gate intercepts before the question UI renders.
- Every path from a paywall has at least 3 forward links — no dead-ends.

---

### Scenario C — Subscription path validation (manual but quick)

| # | Step | Pass criterion |
|---|---|---|
| C1 | Sign in as a regular user (Scenario B) → click any free set | Mock exam loads — confirms subscription gate doesn't block free sets |
| C2 | Sign out, sign in as `admin@example.com` (the bootstrap admin) → click a premium set | Same paywall as Scenario B (admin has no subscription either by default) |
| C3 | (Optional, requires Razorpay live keys) Click "View plans & subscribe" → complete a test purchase → return to `/dashboard` | Badge changes from **Free plan** to **Active plan: pro** |
| C4 | Click the previously-locked premium set | The exam loads (no paywall) |

If you don't have Razorpay test keys configured, skip C3-C4 and instead
run a SQL insert:
```sql
INSERT INTO subscriptions (user_id, plan, status, current_period_end)
VALUES ((SELECT id FROM users WHERE email = 'admin@example.com'),
        'pro', 'active', NOW() + INTERVAL '30 days');
```
Then C4 should pass.

---

### Scenario D — Super Admin: end-to-end content lifecycle

Most of this is automated by checks 4-27 in the smoke test. The
**manual** items below verify the UI surface itself.

| # | Step | Pass criterion |
|---|---|---|
| D1 | Sign in as `admin@example.com` | Redirected to `/admin` |
| D2 | Sidebar nav shows | Dashboard · Users · Questions · Exam Sets · Contacts · FAQs · Runtime Settings · LLM Providers · Payment Providers |
| D3 | **Edit landing copy without restart**: Settings → find `landing.lead_section_heading` → click value → enter new text → Save | Open `/` in another incognito tab — the new heading shows immediately (within ~30s due to settings cache TTL) |
| D4 | Revert the heading | Same — landing reflects within ~30s |
| D5 | **Question CRUD**: `/admin/questions` → "+ New Question" → fill stem, phase, 4 options, mark one correct → Create | Returns to editor at `/admin/questions/<new-id>` |
| D6 | Edit the same question (change stem or option text) → Save changes | List shows the new stem (no "options uniqueness" 500 error — bug fix from earlier turn) |
| D7 | **Exam Set CRUD + linkage**: `/admin/exam-sets` → "+ New Exam Set" → fill name/slug/time-limit (e.g. 15 min) → toggle Premium ON → Create | Row appears with the ⭐ premium badge and "⏱ 15 min" |
| D8 | Click **Edit** on the row → change time limit to 20 → Save | Row updates to "⏱ 20 min" — the field is editable post-create |
| D9 | Click "Manage questions" → search for the question from D5 → check it → "Add selected" | Question appears in the linked list |
| D10 | Reorder via ↑/↓ or "Save order" | Position persists on reload |
| D11 | Click the **free / premium** badge on the parent list page | Badge flips inline, server confirms via PATCH |
| D12 | **Contact delete (lead)**: visit `/admin/leads` → click any **lead** row's Delete button → confirm | Row disappears from the list |
| D13 | **Contact delete (user)**: same page → click any **user** row's Delete (super-admin only) → confirm | Row disappears; that user can no longer log in |
| D14 | **FAQ CRUD**: `/admin/faqs` → "+ New FAQ" → fill question + answer → Create. Then Edit → toggle "Active" off → Save. Then Delete | Inactive FAQ disappears from the public landing immediately |
| D15 | Visit `/` after D14 — verify FAQ section reflects what's in admin | The FAQ list matches `/admin/faqs` (active rows only) |

**Expected outcomes**:
- Every admin write produces an audit_log entry: `audit_logs` table grows.
- Every action visible to a learner produces a journey_events entry too.
- Tail `backend/logs/app.jsonl` while doing D3-D15 — every action shows
  up as a JSON line within ~1 second.

---

### Scenario E — Cleanup / state reset (run before re-running scenarios)

```sql
-- Remove the test Google user from Scenario A so it can be re-tested
DELETE FROM users WHERE email = 'your-google-test-account@gmail.com';

-- Reset bootstrap admin password if needed (rare)
UPDATE users SET password_hash = NULL, role = 'super_admin'
  WHERE email = 'admin@example.com';
-- (then re-run ./scripts/bootstrap.sh which re-hashes BOOTSTRAP_ADMIN_PASSWORD)
```

Or full reset (loses all data — only on dev):
```bash
docker compose down -v        # drops the pgdata volume
./scripts/bootstrap.sh        # rebuilds + reseeds + smoke
```

---

## CI / pre-deploy

Use `./scripts/upgrade.sh` — it bundles:

1. Snapshot guarded tables (users / exam_sessions / payments / …)
2. `alembic upgrade head`
3. Idempotent seeder
4. Restart backend
5. Verify no guarded table lost rows (otherwise exit non-zero — block deploy)
6. **Run the full smoke test** (the 27 checks above)

If `upgrade.sh` is green, manual scenarios A-E should also be green
unless they touch a UI surface that the smoke test doesn't cover. Add
a manual line item here for any new UI feature.

## What this list does NOT cover

- **Real Google OAuth handshake** — the iframe redirect can't be JS-driven;
  scenarios A and B require a human clicking through the Google account
  picker. The smoke test only verifies the **endpoint exists and rejects
  bogus tokens** (check #3).
- **Razorpay live payment flow** — covered by Scenario C3 only when test
  keys are configured. The backend Razorpay verification is unit-tested
  separately in `backend/tests/integration/test_payment_providers.py`.
- **AI tutor** — out of scope for this checklist; LLM responses are
  non-deterministic and need a separate eval harness.
- **Mobile-specific behavior** — covered ad-hoc; for production builds,
  add Lighthouse CI on `/login`, `/`, `/dashboard`, `/exams`.
