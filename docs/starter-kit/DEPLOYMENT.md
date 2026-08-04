# DEPLOYMENT — one VPS, CI-gated, self-healing (D-V in practice)

Target: a single Ubuntu VPS (4–8 GB) running docker-compose behind a
host-level Caddy, deployed by GitHub Actions on merge to main, with
migrations, seeds, smoke tests, and automatic rollback. Everything an
operator does goes through scripts committed to the repo — the server
must be rebuildable from `provision.sh` + `install_app.sh` + backups.

## Topology

```
Internet → Caddy (host service, terminates TLS, HTTP/3)
            ├─ apex domain  → Next.js container (:3001)
            └─ api.<domain> → FastAPI container (:8001)
docker-compose: postgres(pgvector) + redis + backend + frontend
volumes: pgdata, uploads (both in backups)
```

## Provision (once per server) — `provision.sh`

- deploy user + SSH keys, docker, fail2ban (sshd jail)
- ufw: default deny; allow **22/tcp, 80/tcp, 443/tcp AND 443/udp**.
  The udp rule is not optional: Caddy serves HTTP/3 and advertises
  `Alt-Svc: h3` with a 30-day browser memory — **never advertise what
  the firewall eats** (production incident: intermittent per-user
  "connection timed out" that no probe could reproduce).
- Host Caddy with per-site config: security headers, JSON access logs
  with rotation.

## Install (once per app) — `install_app.sh`

- Clone, write `.env` (operator fills secrets), then fresh-DB bootstrap:
  `CREATE EXTENSION vector` → `Base.metadata.create_all` →
  `alembic stamp head` → seed default tenant + settings + demo content.
  (The migration chain intentionally does NOT run from empty — 0001 is a
  stamp baseline. Document this loudly; it bites everyone once.)
- Generate `SMOKE_ADMIN_*` credentials for deploy smoke tests.

## Deploy (every merge) — `deploy.sh` invoked by Actions

Order matters; each step exists because its absence caused an incident:

1. `git fetch` with 3× retry (transient network at the host happens).
2. **Pre-deploy backup** (SQL dump + uploads tar). Refuse to proceed if
   backup fails.
3. Tag current images `:previous` (rollback target).
4. Build images; `up -d postgres redis` FIRST (so a changed DB image is
   actually recreated), then backend/frontend.
5. `alembic upgrade head` — with `transaction_per_migration=True`.
6. Idempotent seeder (runs even on no-op deploys so seed-JSON changes
   land).
7. Smoke tests over real HTTP with the dedicated smoke admin (login,
   key pages, key APIs).
8. ERR trap: any failure between build and smoke → retag `:previous` →
   restore DB from the pre-deploy backup → git reset to start SHA →
   verify `/health` → report. Escape hatch env var to debug in place.

## CI gates (block the merge, not the deploy)

- Full backend pytest (SQLite+fakeredis: fast, service-free), tsc,
  vitest.
- **Migration-drift gate**: bootstrapped scratch DB (create_all + stamp)
  → `alembic check` (models vs head) → `upgrade head` (no-op must not
  crash). Catches model-without-migration drift the normal tests can't.
- Production deploy behind a manual Environment approval.

## Distilled production lessons (each cost real downtime — teach them)

1. Never `git pull` before `deploy.sh` — the script diffs SHAs itself;
   pre-pulling routes it into the no-op path.
2. A deploy script edits itself: fixes to `deploy.sh` take effect the
   NEXT run — critical self-dependent paths must self-restart.
3. `set -euo pipefail` + an empty glob/`tail -n +31` pipeline = silent
   abort. Wrap optional steps in `|| true` subshells.
4. Postgres image changes don't apply with `up -d --no-deps app...` —
   recreate the DB container explicitly (pgvector incident).
5. Two migrations touching one enum in one transaction = prod-only
   failure (`transaction_per_migration=True`, and test with data rows,
   not just empty schemas).
6. Rotating an admin password must never break deploy smoke — dedicated
   smoke account, synced from `.env` by the seeder.
7. Prune old docker images with a retention window or the disk fills.
8. curl-based smoke can't see CORS errors — after releases touching
   origins/headers, do one real-browser check.
9. Firewall vs HTTP/3: allow 443/udp (see Provision).
10. When "some users" report timeouts but you can't reproduce: check
    kernel `[UFW BLOCK]` logs, per-region reachability
    (check-host.net), and remember browser Alt-Svc caches — cache
    clearing doesn't reset them.

## Backups & restore

- Nightly SQL dump + uploads tar, 30-day retention, restore script
  tested (a backup that has never been restored is a hope, not a
  backup). Pre-deploy backups are the rollback substrate.

## Monitoring

- External multi-region uptime checks (free tier is fine) including a
  node in your primary user geography; alerting to email/phone.
- On-server: container restart counts, disk, memory (add swap or
  document the OOM posture), Caddy JSON access logs, app request logs
  with request-ids, admin observability page as the single pane.
