# Release workflow — local → tested → production

The promotion path every change must follow. Designed so backward
compatibility (no data loss, no breaking API contract) is enforced by
the tooling, not just by reviewer attention.

```
   ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
   │  feature/x  │ PR  │  main        │     │  production  │
   │  (laptop)   │ ──► │  (GitHub)    │ ──► │  (cpmaiexam… │
   │             │     │              │     │   prep.com)  │
   └─────────────┘     └──────────────┘     └──────────────┘
       smoke +              CI runs           upgrade.sh
       manual E2E           smoke test        on host
                            (no DB)
```

## Branch model

- **`main`** — the only branch ops promotes from. Always green.
  Protected on GitHub: requires PR review, requires status checks
  to pass.
- **`feature/<short-name>`** — every change starts here. Branch off
  from `main`, work locally, push, open a PR.
- **No long-lived branches.** Feature branches live ≤ 1 week. Long
  branches accumulate merge conflicts and migration ordering bugs.

## Promotion in 6 steps

### 1. Branch + write the change (local)

```bash
cd C:/Users/mssop/Downloads/Project/cpmai/cpmai-prep
git fetch origin
git checkout -b feature/clear-name main
# … edit code …
```

If the change touches the schema:

```bash
docker compose exec backend bash -c \
  'cd /app && alembic revision -m "describe the change" --autogenerate'
# Review the generated migration file. autogenerate is good but not
# perfect — verify it matches what you intended, and that the upgrade()
# is ADDITIVE ONLY:
#   ✅ ADD COLUMN IF NOT EXISTS / ADD INDEX IF NOT EXISTS / CREATE TABLE
#   ❌ DROP TABLE / DROP COLUMN / ALTER TYPE that loses data
git add backend/migrations/versions/<NNNN_*.py>
```

### 2. Verify locally

```bash
# Apply migration to the local DB and run the full smoke
./scripts/upgrade.sh

# Walk the manual E2E checklist for the surface you touched
# docs/e2e-test-plan.md  →  pick scenarios that overlap your change
```

The smoke covers all 27 API checkpoints automatically. The E2E plan
covers the browser-only items (Google sign-in, drag-highlight, etc.).
**Both must be green before you push.**

### 3. Commit + push the branch

```bash
git add -A
git commit -m "feat: <one-line summary>

<body — what changed, why, what the trade-offs were>
"
git push -u origin feature/clear-name
```

### 4. Open a PR on GitHub

- Title: same as the commit subject (`feat:` / `fix:` / `chore:` etc.)
- Body: link any issue/ticket; paste the relevant section of the
  manual E2E checklist with each step ticked
- CI runs automatically (`.github/workflows/backend-ci.yml`,
  `frontend-ci.yml`, `security-scan.yml`). All three must pass.

### 5. Self-review the diff on GitHub

Specific things to check on the PR's **Files changed** tab:

| What | Why |
|---|---|
| New migration is additive only (no `DROP`) | Backward compat — the data-preservation guard catches data loss after the fact, but a forward-only migration is the cleaner contract |
| No new hardcoded secrets | grep your diff for `password=`, `key=`, `token=` |
| No `.env`, `.env.local`, or anything from `backend/logs/` | should be impossible because `.gitignore` covers them, but easy to accidentally `git add -f` |
| API contract changes are documented | If you renamed a field or removed an endpoint, update the relevant `.tsx` consumer at the same time |
| `time_limit_minutes` and other admin-editable settings stay in `EDITABLE` whitelist | If you added a new runtime setting, register it in `backend/app/api/v1/endpoints/admin/settings.py` |

### 6. Merge to `main`

Use **"Squash and merge"** in GitHub so each feature is one commit
on `main`. Don't merge until CI is green.

## Production deploy

```bash
# On the production host (VPS, Render, Fly, K8s pod, whatever)
cd /opt/cpmai-prep
git fetch origin
git pull --ff-only origin main

./scripts/upgrade.sh
```

`upgrade.sh` does, in order:

1. Snapshot row counts of every guarded table
2. Rebuild + force-recreate the backend container (picks up new code)
3. Wait for `/health`
4. `alembic upgrade head` (applies any new migrations)
5. Run `seeds/seed.py` (idempotent — adds new defaults, never overwrites)
6. **Re-snapshot and refuse to declare success if any guarded table
   lost rows** — this is the load-bearing safety net
7. Run the 27-step smoke test against the live stack
8. Exit non-zero if anything failed (your platform's deploy then halts)

**If step 6 or 7 fails, the deploy aborts.** Roll back the running
container to the previous image (your platform's "previous deployment"
button) and read `backend/logs/app.jsonl` to debug.

## Backward-compatibility rules

These are the ones that matter for an app with real users:

### Schema migrations

- **Always additive.** New columns are nullable or have a default.
  Renames are done in two releases: release N adds the new column +
  dual-writes; release N+1 drops the old column once the old code is
  no longer running.
- **Never `DROP COLUMN`** in the same release as the code change that
  stops using it. There's always a window where old containers are
  still running and need the column.
- **Use `IF NOT EXISTS`** on `CREATE TABLE` and `ADD COLUMN` so
  re-running the migration is safe.
- **`downgrade()` raises `NotImplementedError`** — forward-only is the
  canonical pattern in this repo. Roll back by deploying an older
  image, not by reversing a migration.

### API contracts

- **Adding a field to a response** — safe. Old clients ignore it.
- **Adding an optional field to a request body** — safe.
- **Renaming or removing a field** — breaking. Add the new field,
  ship one release with both, update clients, then ship a second
  release that drops the old field.
- **Adding a new required field** — breaking. Use an optional default
  for one release, then promote to required.
- **Changing the URL of an endpoint** — breaking. Add the new URL,
  keep the old one redirecting/aliasing for one release, then drop
  the old.

### Storage / state

- **The seeder must always be idempotent.** Re-running it on a
  populated DB must be a no-op. New defaults you want to apply to
  existing rows go in a migration's `op.execute("UPDATE …")`, NOT in
  the seeder.
- **Per-attempt local state** lives in `localStorage` keyed by
  `attempt.id` and is cleared on submit. If you change the storage
  shape, **bump the key prefix** so old keys don't collide
  (`cpmai.exam.annotations.v2.<id>`).

### Settings

- **Adding a `system_settings` key** — safe. Add it to the EDITABLE
  whitelist in `admin/settings.py` and to `seed.py`'s defaults.
- **Removing one** — leave the row, stop reading it. Drop the key
  in a later release once you're sure no code path reads it.

## Environment hierarchy (recommended)

```
local (laptop)            staging (optional)        production
─────────────             ──────────────────        ──────────
docker-compose            same docker-compose       Render / Fly / VPS
.env on disk              env vars on host          env vars in platform
test data                 a clone of prod data      real user data
                          OR fresh test data
```

A staging environment that mirrors production is the single best
investment for catching prod-only bugs (TLS edge cases, rate-limit
behavior, real DNS, real Razorpay test mode). If you can't run one
yet, the next-best thing is rigorous adherence to this workflow.

## Pre-push checklist (paste into your terminal)

```bash
# Run this before every `git push` to a feature branch:
./scripts/upgrade.sh \
  && git diff --stat origin/main..HEAD \
  && echo "✓ ready to push"
```

If `upgrade.sh` exits non-zero, do not push.

## When to break the rules

- **Hotfix to production**: branch off `main` as `hotfix/<name>`,
  push directly to a PR, fast-track review, merge. The ceremony
  matters less than getting users unblocked. But still run
  `./scripts/upgrade.sh` first — the data-preservation guard isn't
  optional.
- **Schema migration that's not additive (e.g., dropping a column
  with no users left on old code)**: write a 3-step plan in the PR
  body, get explicit approval, deploy each step on its own.

## Rollback

If a deploy goes bad:

```bash
# 1. Roll the container image back
docker compose pull backend  # if your CI tags releases
docker compose up -d --force-recreate backend
# OR on Render/Fly: hit "previous deployment" in the dashboard

# 2. Restore the DB from the last automated backup
pg_restore --clean --if-exists --dbname=$DATABASE_URL latest.dump

# 3. Re-run the smoke against the rolled-back stack
python scripts/smoke_admin_crud.py
```

**Backups are not provisioned by this repo** — set them up in your
platform before your first real signup. Render/Fly/RDS all have
one-click backup retention. Without backups the data-preservation
guard tells you when something broke, but you can't recover.

## TL;DR

| When | Run |
|---|---|
| Before every push | `./scripts/upgrade.sh` (= migrations + smoke + safety guard) |
| After PR merge to `main` | CI runs the same smoke automatically |
| On production host | `git pull && ./scripts/upgrade.sh` |
| Before merging a schema change | confirm migration is additive + IF NOT EXISTS guarded |
| Before changing a response field | confirm the corresponding frontend type + caller is updated in the same PR |
