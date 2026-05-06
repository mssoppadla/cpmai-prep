# Deployment lifecycle

This document covers:

1. Picking a Google account for production
2. One-command setup (local + first-time prod)
3. One-command upgrade (every subsequent deploy)
4. The data-preservation guarantee
5. Where every config setting lives
6. Hosting options for `cpmaiexamprep.com`

---

## 1. Which Google account to use

The Google account you pick **owns** the OAuth client and all Cloud
project assets for the lifetime of the app. Choose carefully.

| Option | Use when | Trade-off |
|---|---|---|
| Workspace admin on the domain (e.g. `admin@cpmaiexamprep.com`) | You have or will set up Google Workspace | Best — survives team changes; dies with the domain, not with a person. |
| Dedicated Gmail like `cpmaiexamprep.admin@gmail.com` | No Workspace yet | Acceptable — keep recovery email/phone in your password manager. Use 2FA + a hardware key. |
| Your personal Gmail | Quick personal experiments only | Avoid for production. If you lose access (job change, account compromise), the OAuth client and Cloud project go with you. |

**Whichever account you pick**, immediately add a second trusted person
as **Project Owner** in
[GCP IAM](https://console.cloud.google.com/iam-admin/iam) so the
project is never single-keyed. Document the chosen account in your
team's password manager / runbook.

For the actual Cloud Console steps to create the OAuth client, see
[`docs/google-auth-setup.md`](google-auth-setup.md).

---

## 2. One-command setup

`scripts/bootstrap.sh` — first-time bringup. Idempotent, safe to re-run.

```bash
./scripts/bootstrap.sh
```

What it does:

1. **Generates `backend/.env`** from `backend/.env.example` if missing.
   Fresh `SECRET_KEY`, `ENCRYPTION_KEY`, and `BOOTSTRAP_ADMIN_PASSWORD`
   are generated. **An existing `backend/.env` is never overwritten.**
2. **Generates `frontend/.env.local`** from the template if missing.
3. **Starts the docker stack** (postgres + redis + backend).
4. **Waits for `/health`**.
5. **Schema convergence**:
   - Fresh DB → `Base.metadata.create_all()` then `alembic stamp head`
   - Existing DB without alembic table → `alembic stamp 0003` then `alembic upgrade head`
   - Existing DB with alembic table → just `alembic upgrade head` (additive)
6. **Runs the idempotent seeder** (`backend/seeds/seed.py`):
   default `system_settings` (skip on conflict), 6 CPMAI topics
   (skip on conflict), super-admin (only if no super-admin exists),
   sample questions + sets (only if their tables are empty).
7. **Runs the smoke test** (`scripts/smoke_admin_crud.py`).

After it finishes, the admin password is in `backend/.env`
(`BOOTSTRAP_ADMIN_PASSWORD`). Frontend isn't started by this script —
run `cd frontend && npm install && npm run dev` separately so HMR
works on the host.

---

## 3. One-command upgrade

`scripts/upgrade.sh` — every-deploy entry point. Use this on any
environment that has been bootstrapped.

```bash
./scripts/upgrade.sh
```

What it does, in order:

1. **Snapshot** row counts of every guarded table (`users`,
   `exam_sessions`, `payments`, `subscriptions`, `leads`,
   `audit_logs`, `journey_events`, `exam_attempt_answers`).
2. **Migrate**: `alembic upgrade head` — applies any pending migrations.
3. **Seed**: re-runs the idempotent seeder. Adds new defaults
   (e.g. when you add a new `system_settings` key) without touching
   existing rows.
4. **Restart** the backend container so it picks up new code/env.
5. **Verify**: re-snapshots and **fails the deploy** if any guarded
   table's row count went DOWN. The exit code is non-zero — your CI
   job stops, ops can investigate.
6. **Smoke test**: full admin-CRUD walkthrough.

If any step fails, the script exits non-zero. The data-preservation
guard is the load-bearing safety net — even a buggy migration that
accidentally truncates `users` is caught here.

---

## 4. Data-preservation guarantee

Three independent safeguards keep your user base intact across every deploy:

### Safeguard 1: additive-only migrations

Every alembic revision in `backend/migrations/versions/` must be
purely additive. The repo convention:

- **OK**: `ADD COLUMN`, `ADD INDEX`, `CREATE TABLE`, raising
  `NotImplementedError` in `downgrade()`
- **NOT OK**: `DROP TABLE`, `DROP COLUMN`, `ALTER TYPE` that loses
  data, `TRUNCATE`

`0004_google_auth.py` is the model: `ALTER COLUMN ... DROP NOT NULL`,
`ADD COLUMN IF NOT EXISTS`, `CREATE UNIQUE INDEX IF NOT EXISTS`. Even
if run twice on the same DB, no rows are touched and no error is raised.

### Safeguard 2: idempotent seeder

`backend/seeds/seed.py` follows these rules:

| What | Rule |
|---|---|
| `system_settings` | skip on conflict (preserves admin overrides) |
| `topics` | skip on conflict |
| Super-admin | created only if no `super_admin` exists |
| Sample questions | inserted only if `questions` is empty |
| Sample exam sets | inserted only if `exam_sets` is empty |

Re-running it on a populated DB is a no-op. **No `DELETE`, no `TRUNCATE`,
no `UPDATE` on existing rows.**

### Safeguard 3: pre/post snapshot guard

`scripts/preserve_users_check.py` snapshots and verifies guarded
tables. The default snapshot lives in `~/.cpmai-preserve-snapshot.json`.
If any count decreased, the verify command exits non-zero — `upgrade.sh`
treats that as deploy failure.

To verify guard works (manually), restore a known-good DB backup before
trying again. The guard never auto-restores; it just refuses to
declare success.

---

## 5. Configuration locations

Single source of truth per environment.

### Local development

| File | What's in it | Generated by |
|---|---|---|
| `backend/.env` | Database URL, secrets, Razorpay test keys, `BOOTSTRAP_ADMIN_*`, `GOOGLE_OAUTH_CLIENT_ID` | `bootstrap.sh` if absent; never overwritten thereafter |
| `frontend/.env.local` | API URL, `NEXT_PUBLIC_GOOGLE_CLIENT_ID`, `NEXT_PUBLIC_RAZORPAY_KEY_ID` | Copied from `.env.example`; edit manually |
| `docker-compose.yml` | Container topology, host port mappings | Committed |

### Production

Production uses the same env-file shape. Where the file actually lives
depends on the host:

| Host | File | How env is set |
|---|---|---|
| Docker on a VPS | `backend/.env` (mounted) | Edit on the server, `docker compose up -d --force-recreate` |
| Vercel (frontend) | — | Set `NEXT_PUBLIC_*` in Vercel dashboard → "Environment Variables" |
| Render / Railway / Fly.io (backend) | — | Set as service env vars in the platform dashboard |
| Kubernetes | `backend/.env` via Secret + envFrom | Apply with `kubectl apply -f` (do not commit) |

The secrets (`SECRET_KEY`, `ENCRYPTION_KEY`, Razorpay live keys, OAuth
secrets) **must be managed outside git**. The `.env.example` files
are tracked so devs know which vars to set; the live `.env` files are
in `.gitignore`.

### Google OAuth — config goes in three places, all sharing one Client ID

| Location | Setting | Value |
|---|---|---|
| GCP Console → Web client → Authorized JS origins | (URL list) | `https://cpmaiexamprep.com`, `https://www.cpmaiexamprep.com`, `http://localhost:3000` |
| `backend/.env` on prod | `GOOGLE_OAUTH_CLIENT_ID` | The Client ID from Google |
| `frontend/.env.production` (or platform UI) | `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | The **same** Client ID |

Mismatch → 401 with "Audience mismatch" on every Google sign-in. See
[`google-auth-setup.md`](google-auth-setup.md) for screenshots and the
common-failure table.

---

## 6. Hosting `cpmaiexamprep.com`

You haven't picked a host yet. The repo runs the same on any of these
without code changes:

### Option A — VPS with Docker (cheapest, most control)

- Provider: Hetzner, DigitalOcean, Linode, Vultr (~$5–10/mo)
- DNS: point `cpmaiexamprep.com` and `api.cpmaiexamprep.com` at the VPS
- Reverse proxy: Caddy or Nginx with auto-TLS (Caddy is simplest)
- Deploy:
  1. Clone repo to `/opt/cpmai-prep`
  2. Create `backend/.env` with real secrets + production
     `GOOGLE_OAUTH_CLIENT_ID`, `CORS_ORIGINS`, `ALLOWED_HOSTS`
  3. `./scripts/bootstrap.sh` (one time)
  4. `./scripts/upgrade.sh` on every release

### Option B — Managed platform (zero ops)

- Frontend on **Vercel** — connect the GitHub repo, set
  `NEXT_PUBLIC_*` env vars in the dashboard, every push to `main`
  builds + deploys. Free for hobby; ~$20/mo for production.
- Backend on **Render** or **Railway** — runs `backend/Dockerfile`,
  set env vars in the dashboard. Add a managed Postgres + Redis
  add-on. ~$10–15/mo.
- Schema migrations run via the platform's "release command" feature
  pointing at `alembic upgrade head` — most platforms support this.

### Option C — AWS / GCP / Azure

- Backend in ECS/Cloud Run/App Service, RDS/Cloud SQL for postgres,
  ElastiCache/Memorystore for redis. Frontend in S3+CloudFront /
  Cloud Storage / Static Web Apps.
- Pricier (~$50/mo minimum for small footprint), but you get autoscale
  and IAM/audit baked in.

For all three, the contract with this repo is: provide a Postgres URL,
a Redis URL, env-var secrets, and run `alembic upgrade head` on
deploy. The bootstrap/upgrade scripts cover the rest.

---

## 7. CI workflow (recommended)

```yaml
# .github/workflows/deploy.yml
name: deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: SSH to prod and upgrade
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.PROD_HOST }}
          username: deploy
          key: ${{ secrets.PROD_SSH_KEY }}
          script: |
            cd /opt/cpmai-prep
            git pull
            ./scripts/upgrade.sh
```

The upgrade script's data-preservation guard is the safety net. Even
if a developer slips a bad migration onto `main`, the count check
fails before the deploy is marked successful, and the platform's
rollback flow can pull the prior image.

---

## 8. Rollback

If `upgrade.sh` failed at the data-preservation check:

```bash
# 1. Restore DB from your last backup (this is your responsibility — see below)
pg_restore --clean --if-exists --dbname=$DATABASE_URL latest.dump

# 2. Roll the app container back to the previous image
docker compose pull backend  # if using a tagged release
docker compose up -d backend

# 3. Re-run the smoke test
python scripts/smoke_admin_crud.py
```

**Backups are not handled by this repo.** Set them up in your platform:

- VPS: cron a `pg_dump` to S3 / Backblaze every hour
- Render/Railway: enable platform-managed daily backups + PITR
- Cloud SQL/RDS: enable automated backups with 7-day retention

Without backups, the data-preservation guard tells you that a deploy
broke things, but you can't recover. **Set up backups before your
first real user signs up.**

---

## 9. Daily operations

| Task | Command |
|---|---|
| Tail the user-journey log | `tail -f backend/logs/app.jsonl \| jq .` |
| Find one user's journey | `grep '"user_id":42' backend/logs/app.jsonl \| jq .` |
| Run smoke test against prod | `BASE_URL=https://api.cpmaiexamprep.com/api/v1 ADMIN_EMAIL=... ADMIN_PASSWORD=... python scripts/smoke_admin_crud.py` |
| Inspect DB | `docker compose exec postgres psql -U cpmai -d cpmai_prep` |
| Promote a Google user to admin | `UPDATE users SET role='admin' WHERE email='x@y'` |
| Reset DB (DEV ONLY) | `docker compose down -v && ./scripts/bootstrap.sh` |
| Add a new migration | `docker compose exec backend bash -c 'cd /app && alembic revision -m "..." --autogenerate'` |

The last one is the only weekly muscle: when you add a new column or
table to a model, run autogenerate, review the file (alembic isn't
perfect), commit it, and `upgrade.sh` will apply it on next deploy.
