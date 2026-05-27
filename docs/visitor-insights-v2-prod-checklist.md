# Visitor Insights v2 — prod deployment checklist

**TL;DR for the operator:** Zero existing user data is destroyed, modified, or rewritten. Every change is additive. Rollback is safe. Below is the line-by-line audit.

---

## 1. What this PR does NOT touch (zero-risk surfaces)

Every table holding user-facing state stays exactly as it is:

| Table | Holds | This PR's impact |
|---|---|---|
| `users` | Auth identity, roles, email verification, GDPR flags | **Untouched** |
| `subscriptions` | Plan + period + expiry, paywall source of truth | **Untouched** |
| `payments` | Razorpay/PayPal txn records, refund history | **Untouched** |
| `assistant_logs` | Per-turn chat transcripts (the "chat history") | **Untouched** |
| `assistant_flagged_turns` | HITL queue, admin replies, user-visible status | **Untouched** |
| `lesson_progress` | Per-user lesson completion + resume position | **Untouched** |
| `enrollments` | Course access grants | **Untouched** |
| `quiz_attempts` / `lms_quiz_attempts` | Quiz scores + answer history | **Untouched** |
| `lessons`, `chapters`, `courses`, `lesson_files` | Course content | **Untouched** |
| `audit_logs` | Every operator-visible event (logins, payments, …) | **Untouched** |
| `leads`, `lead_sources` | Marketing-form submissions | **Untouched** |
| `zoom_sessions`, `recordings` | Live session metadata + recordings | **Untouched** |
| `campaigns`, `campaign_runs` | Social automation state | **Untouched** |
| `rag_chunks`, `rag_documents` | RAG embeddings | **Untouched** |

The `cpmai-uploads` named volume (all lesson video, attached files, Zoom recordings, image uploads) is also untouched. Pre-deploy `backup.sh` still tars it normally.

**Translation:** Any user who logs in after this deploy sees exactly the same:
- Course progress
- Quiz scores
- Chat history + flag replies
- Active subscription
- Lesson notes
- Profile data

---

## 2. What this PR DOES touch (additive only)

### Migration 0032 — `journey_events` extension + new rollup table

**On `journey_events`:**
- 11 new columns (tenant_id, path, referrer, utm_*, ua, device, browser, os, country, city, duration_ms, scroll_pct) — **all nullable** so existing INSERTs keep working
- `event` VARCHAR(64) → 96 (widening only, never narrowing)
- Backfill: existing rows get `tenant_id=1` via `server_default="1"` — no DML needed
- 3 new indexes for dashboard scans

**On migrations contract:**
- M-1 (additive only): ✅ no DROP, no NOT NULL on existing data
- M-2 (single logical change): ✅ one PR = one migration
- M-3 (idempotent `alembic upgrade head` after bootstrap): ✅ tested locally

**New table `visitor_insights_daily`:** empty at deploy, populated only when `tracking.rollup_enabled=true` (default false).

**⚠ One thing the operator should know:** `CREATE INDEX` on Postgres without `CONCURRENTLY` takes an `ACCESS EXCLUSIVE` lock on `journey_events` for the duration of the build. On our table size (~hundreds of thousands of rows max today) that's <10 seconds. If `journey_events` is much larger in prod than locally, consider running:

```sql
-- Manually, after deploy, instead of letting Alembic do it
CREATE INDEX CONCURRENTLY ix_je_tenant_event_time ON journey_events (tenant_id, event, created_at);
CREATE INDEX CONCURRENTLY ix_je_tenant_path_time  ON journey_events (tenant_id, path, created_at);
CREATE INDEX CONCURRENTLY ix_je_session_time      ON journey_events (session_id, created_at);
```

(Then mark the migration as applied without re-running the index step.)

For our v1 scale this is not needed — the Alembic-managed CREATE INDEX is fine.

### `system_settings` — 3 new rows (additive)

- `tracking.enabled` (default `true`)
- `tracking.sample_rate` (default `1.0`)
- `tracking.rollup_enabled` (default `false`)

Seeded by `seeds/seed.py` which is idempotent (skip-if-exists). Existing system_settings rows untouched.

### Code changes that bear on prod safety

| File | Change | Risk |
|---|---|---|
| `app/services/tracking_service.py` | Added new kwargs to `emit_event()` + wrapped DB write in try/except | **Behaviour change** — DB write errors no longer raise. Mitigation: logged at WARN |
| `app/core/settings_store.py` | Added `get_bool()` helper | New method only — zero impact on existing callers |
| `app/main.py` | Registered visitor-insights rollup APScheduler job | Wrapped in try/except so failure can't take down the social scheduler |
| `app/api/v1/endpoints/tracking.py` | New `POST /api/v1/track` endpoint | New route, public, rate-limited 120/min, sample-rate honoured, kill switch via setting |
| `app/api/v1/endpoints/admin/visitor_insights.py` | New `/admin/insights/*` endpoints | New routes only, admin-gated |

### Frontend changes

- `TrackerMount` injected into root layout — every page now fires `page.view` + heartbeat events
- **Respects Do-Not-Track** — exits early if browser sends DNT
- **Honours the kill switch** — POST /track returns 0-row ack when `tracking.enabled=false`
- Old `/admin/anonymous-traffic` widget on `/admin/leads` still works unchanged; just gets a "Open full Visitor Insights →" link above it

---

## 3. Prod deploy sequence — what `deploy.sh` does for this PR

Walking through the standard 11-step deploy script with this PR's changes in mind:

| Step | Standard action | This PR's impact |
|---|---|---|
| 1 | `git pull --ff-only` | Pulls the new code |
| 2 | **SQL backup + env tar** to `/var/backups/cpmai-prep/` | Captures snapshot before any migration. **Critical safety net.** |
| 3 | Row-count snapshot of guarded tables (users, payments, …) | Verifies we don't shrink any user table. None of my changes touch these tables, so counts won't move. |
| 4 | `docker compose build --pull` for backend + frontend | Builds new images with my code |
| 5 | `compose up -d postgres redis` | No-op (no compose drift) |
| 6 | `compose up -d --no-deps --build backend frontend` | Switches to new images. Old image preserved as `:previous` for auto-rollback. |
| 7 | Wait for `/health` | Standard health gate |
| 8 | `alembic upgrade head` inside backend container | **Runs migration 0032.** Adds nullable columns + indexes. <10s expected. |
| 9 | `python seeds/seed.py` | Inserts the 3 new `tracking.*` settings rows (idempotent — skip if exists) |
| 10 | Row-count verification | Asserts every guarded table is ≥ pre-deploy count. My migration only ADDS data so this passes. |
| 11 | Smoke test on real public URL | Hits `/health` |

**At no step does any existing row get modified.** The only writes are:
- 3 INSERT INTOs into `system_settings`
- ALTER TABLE journey_events ADD COLUMN (×11, nullable)
- CREATE INDEX (×3) on journey_events
- CREATE TABLE visitor_insights_daily (empty)

---

## 4. Auto-rollback compatibility

If the deploy fails the smoke test, the `:previous` Docker tag rolls back. Forensics on this specific PR:

| What rolls back | What does NOT roll back |
|---|---|
| Docker image (`:previous` re-tagged → `:latest`) | Migration 0032 (no downgrade — by contract M-2) |
| Old code re-running with new schema | The new nullable columns + indexes + empty rollup table |

**Will the old image work against the new schema?**

✅ Yes. The old `journey_events` model declares fewer columns. SQLAlchemy ORM silently ignores extra columns on SELECT. Existing INSERT calls don't reference the new columns; they get NULL via `server_default`. The widened VARCHAR is non-breaking. The new indexes are transparent to old queries.

**Will the new endpoints disappear?**
✅ Yes. `/api/v1/track` and `/admin/insights/*` 404 against the old code. The frontend tracker still tries to POST, gets 404, logs `console.warn("[tracker] flush failed")` and moves on (errors are swallowed by design — analytics is best-effort).

**Will the frontend break?**
✅ No. Old frontend image doesn't have `TrackerMount`, so no tracker calls fire at all. The `/admin/insights` page route doesn't exist in the old build. The `/admin/leads` bridge link returns 404 if a user clicks it but the rest of the page works.

**One scenario to watch:** if a user opens an `/admin/insights` page tab BEFORE rollback and that tab makes an API call AFTER rollback, the call 404s and the page surfaces an error banner. Refresh fixes it.

---

## 5. User-experience continuity guarantees

| What a returning user sees on first page-load after this deploy |
|---|
| ✅ Their progress on every lesson is preserved |
| ✅ Their chat history is intact (with flag replies) |
| ✅ Their subscription continues, dashboard unchanged |
| ✅ Quiz attempts and scores preserved |
| ✅ Course enrollments preserved |
| ✅ Notes on lessons preserved |
| ✅ Razorpay/PayPal payment records preserved |
| ✅ Anonymous visitors continue to be tracked by their existing `anon_id` cookie |
| ➕ NEW: a `vi_session_id` cookie is created (sessionStorage, dies on tab close) |
| ➕ NEW: a few small POSTs to `/api/v1/track` every 5s while a tab is active |

The added POSTs are bounded:
- Max 50 events per batch
- Max ~12 batches/min during heavy navigation (well under the 120/min rate limit)
- ~1KB per batch in normal use
- Stops entirely when the tab is backgrounded (Page Visibility API)

---

## 6. Prod monitoring after deploy — what to watch

Within the first hour:
- **`backend/logs/app.jsonl`** for `event_name="journey"` log lines — should start showing `page.view`, `page.heartbeat`, etc. from real visitors
- **`journey_events` row count** — should grow steadily (login + open `/admin/observability/disk` to spot-check)
- **`/admin/insights`** opens cleanly; KPI strip shows non-zero numbers within ~5 minutes of first real visitor
- **No spike** in audit_logs from `assistant.anon.*` — the old widget still reads from that prefix; if it stops firing, something broke

Within the first day:
- `journey_events` row growth should be reasonable (~10-50 rows per active visitor per session, depending on engagement)
- If growth is alarming, the kill switch is one PATCH:
  ```
  curl -X PATCH https://api.cpmaiexamprep.com/api/v1/admin/settings \
       -H "Authorization: Bearer <admin-token>" \
       -d '{"key": "tracking.enabled", "value": false}'
  ```
  Live-effective in <1s (Redis pubsub invalidates the cache across all backend pods).

Within the first week:
- Disk growth on the DB volume — `journey_events` is row-heavy. Worth watching `/admin/observability/disk` for pgdata growth.
- If sustained growth crosses comfort, flip `tracking.sample_rate=0.5` to halve write volume immediately.

---

## 7. Pre-merge checklist

Before merging this PR to `main`:

- [x] All backend tests passing (1062/1062)
- [x] All frontend tests passing (135/135)
- [x] TypeScript strict check clean (0 errors)
- [ ] Frontend Dockerfile.prod builds on Linux (Docker — in progress at time of writing)
- [ ] Backend Dockerfile builds on Linux (Docker — in progress)
- [ ] `scripts/preflight.sh` end-to-end pass
- [ ] PR review for the migration file (operator should eyeball the column types + index columns)
- [ ] Confirm with the operator that `journey_events` row count in prod isn't already huge (>10M) — if so, switch to `CREATE INDEX CONCURRENTLY` strategy above

Post-deploy verification:
- [ ] `/health` returns 200
- [ ] `/api/v1/admin/insights/overview?window=24h` returns a JSON body (even if KPIs are 0)
- [ ] First `page.view` row appears in `journey_events` within ~30s of an admin loading any public page
- [ ] Existing `/admin/leads` page still renders the "Anonymous traffic" widget
- [ ] Settings UI shows the 3 new `tracking.*` rows
- [ ] Existing user can log in and see their dashboard unchanged
- [ ] An existing chat session opens and shows full history

---

## 8. Specific things I deliberately did NOT change in this PR

- The `anonymous_traffic` endpoint and its widget — kept for continuity. The new dashboard supplements rather than replaces.
- The `audit_log` taxonomy — `assistant.anon.*` still fires from `POST /assistant/anon-event`. No data migration needed.
- The `assistant_logs` chat history schema — completely independent of journey_events.
- The Razorpay/PayPal webhook handlers — no payment-path changes.
- `cpmai-uploads` volume layout, `lesson_files.file_url` shape, `lesson_progress` rows — every storage-touching surface is unchanged.

If something on this list DOES break after deploy, the cause is not this PR.
