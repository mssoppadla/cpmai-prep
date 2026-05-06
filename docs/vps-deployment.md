# VPS deployment runbook

End-to-end production deployment for **cpmaiexamprep.com** on an
Ubuntu 24.04 VPS, with backup, rollback, and zero-data-loss guarantees.

This runbook is the *only* document you need on the VPS itself. The
scripts under [`scripts/vps/`](../scripts/vps/) do the heavy lifting; this
file explains *when* to run *which* and what to expect.

> **Substitute throughout this runbook**:
> - `<VPS_IP>` — the public IP of your VPS (kept out of this repo on purpose)
> - `<your-google-client-id>` — your OAuth client ID from Google Cloud Console
> - the deploy user defaults to `deploy`; override with `DEPLOY_USER=…` env var
>
> Treat the VPS IP, hostname, and SSH details as **operator secrets** — keep
> them in a private password manager, not in any file in this repo.

---

## Topology

```
┌──────────────────────────────────────────────────────────────────┐
│ Ubuntu 24.04 VPS  (public IP kept private)                       │
│                                                                  │
│  ┌─────────────────────┐   :80, :443                             │
│  │ Caddy (host pkg)    │ ──────── auto-TLS via Let's Encrypt    │
│  │  /etc/caddy/        │                                          │
│  └─────────┬───────────┘                                          │
│            │ reverse_proxy localhost:3000  (apex + www)           │
│            │ reverse_proxy localhost:8000  (api.*)                │
│            ▼                                                      │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ docker compose stack  (loopback-only ports)                  │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │ │
│  │  │ frontend │  │ backend  │  │ postgres │  │ redis    │      │ │
│  │  │ :3000    │  │ :8000    │  │ internal │  │ internal │      │ │
│  │  └──────────┘  └──────────┘  └────┬─────┘  └──────────┘      │ │
│  │                                   │                          │ │
│  │                              pg_dump → backups dir on host   │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Other stacks on the same box (e.g. n8n) — keep off ports 80/443 │
└──────────────────────────────────────────────────────────────────┘
```

DNS (in your domain registrar):

| Record | Value |
|---|---|
| `cpmaiexamprep.com`        A | `<VPS_IP>` |
| `www.cpmaiexamprep.com`    A | `<VPS_IP>` |
| `api.cpmaiexamprep.com`    A | `<VPS_IP>` |

---

## Phase 1 — One-time VPS setup

Do this **once** on a fresh VPS. Idempotent — re-running is safe.

### 1.1 SSH in as root

```bash
ssh root@<VPS_IP>
```

### 1.2 Stop n8n on ports 80/443 (if it's grabbing them)

Hostinger's n8n preset typically binds 80/443. Caddy needs both for ACME +
HTTPS. Move n8n to high ports OR disable its public listener:

```bash
docker ps                       # find the n8n / traefik container
ss -ltnp | grep -E ':(80|443) ' # confirm what's listening
# If n8n owns 80/443:
docker stop <n8n-or-traefik-id>
# Then in n8n's compose.yml change ports to e.g. 5678:5678 (only) and
# expose it via Caddy as n8n.cpmaiexamprep.com — or skip and don't expose it.
```

### 1.3 Run provision.sh

```bash
git clone https://github.com/mssoppadla/cpmai-prep.git /tmp/cpmai-prep
sudo bash /tmp/cpmai-prep/scripts/vps/provision.sh
```

What it does:

- apt update + upgrade + unattended-upgrades for security patches
- Installs **Docker CE** + Compose plugin
- Installs **Caddy** (host package, auto-TLS via Let's Encrypt)
- Configures **ufw** firewall: 22, 80, 443 only — denies everything else
- Enables **fail2ban** (protects SSH against brute-force)
- Creates the `deploy` user in `docker` + `sudo` groups (NOPASSWD)
- Creates `/opt/cpmai-prep`, `/var/backups/cpmai-prep`, `/var/log/caddy`
- Warns if anything is still occupying ports 80/443 (n8n!)

The script prints a temp password for the `deploy` user. **Copy it.** Then
upload your SSH key and disable password auth:

```bash
# from your laptop
ssh-copy-id deploy@<VPS_IP>

# back on the VPS, as root
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/'             /etc/ssh/sshd_config
systemctl reload ssh
exit
```

### 1.4 Point DNS

In your domain registrar, set the three A records to `<VPS_IP>`.
Caddy will auto-issue TLS certificates on the first hit to each hostname —
nothing else to configure.

---

## Phase 2 — First-time app install

```bash
ssh deploy@<VPS_IP>
git clone https://github.com/mssoppadla/cpmai-prep.git /opt/cpmai-prep
cd /opt/cpmai-prep
./scripts/vps/install_app.sh
```

The script will prompt for:

| Prompt | What to enter |
|---|---|
| Production domain | `cpmaiexamprep.com` |
| Google OAuth Client ID | `<your-google-client-id>` (or blank to disable) |
| Razorpay Key ID | `rzp_live_…` (or `rzp_test_…` until live) |
| Razorpay Key Secret | (matching secret) |
| Razorpay Webhook Secret | (from Razorpay dashboard → Webhooks) |
| Bootstrap admin email | `admin@cpmaiexamprep.com` |

It generates fresh `SECRET_KEY`, `ENCRYPTION_KEY`, and a 24-char admin
password (printed to the terminal — **WRITE IT DOWN**, and stored in
`backend/.env`). It then:

1. Writes `backend/.env` and `frontend/.env.local` (mode 0600).
2. Installs `infra/Caddyfile` to `/etc/caddy/Caddyfile` with your domain
   substituted, reloads caddy.
3. Builds production images (`Dockerfile.prod`, `docker-compose.prod.yml`).
4. Runs `alembic upgrade head` + idempotent seeder.
5. Installs the **daily 02:30 backup cron**.
6. Runs the 27-step smoke test.

When it returns "✓ Install complete", visit `https://cpmaiexamprep.com/login`,
sign in with the admin email + the password the script printed.

### 2.1 Configure Google OAuth redirect URI

In **https://console.cloud.google.com/apis/credentials** → your OAuth client →
**Authorized redirect URIs**, add:

- `https://cpmaiexamprep.com`
- `https://cpmaiexamprep.com/login`
- `https://www.cpmaiexamprep.com`
- `https://www.cpmaiexamprep.com/login`

Save. Google takes a few minutes to propagate. Test at `/login`.

### 2.2 Configure Razorpay webhook

In Razorpay dashboard → **Settings → Webhooks → Add new**:

- URL: `https://api.cpmaiexamprep.com/api/v1/payments/webhook`
- Active events: `payment.captured`, `payment.failed`, `order.paid`
- Secret: the same value you entered for `RAZORPAY_WEBHOOK_SECRET`

---

## Phase 3 — Day-to-day deploys

This is the only command you'll run for new features and bug fixes:

```bash
ssh deploy@<VPS_IP>
cd /opt/cpmai-prep
./scripts/vps/deploy.sh
```

What it guarantees:

| Step | Why it matters |
|---|---|
| `git pull --ff-only` | refuses non-fast-forward (no surprise rewrites) |
| **Pre-deploy backup** | `pre-deploy-<sha>.sql.gz` — your rollback target |
| Snapshot row counts (users, payments, etc.) | so step 8 can verify no data lost |
| Build images (`docker compose build`) | bakes new `NEXT_PUBLIC_*` values |
| Recreate `backend` + `frontend` only | postgres + redis stay up = no downtime for stateful services |
| `alembic upgrade head` | additive migrations only (forward-only `downgrade`) |
| Idempotent seeder | tops up new defaults; **never** overwrites existing rows |
| **Data-preservation verify** | refuses to declare success if any guarded row count decreased |
| **27-step smoke test** | login → CRUD → linkage → public — fail = rollback signal |

Runtime: ~90 seconds for a typical change. Frontend rebuild adds ~60s if
package-lock changed.

### 3.1 If deploy fails

The pre-deploy backup is the safety net. Roll back with:

```bash
./scripts/vps/restore.sh latest        # OR explicit path
```

`latest` resolves to the newest backup in `/var/backups/cpmai-prep/` —
which after a failed deploy is the `pre-deploy-<sha>.sql.gz` you just took.
`restore.sh` itself takes a *pre-restore* backup before dropping data, so
even a wrong restore is reversible.

### 3.2 Backward-compatibility rules

The deploy script protects data, but only if migrations follow these rules:

- **Additive only.** New columns must be nullable or have a default; new
  tables are fine; new indexes are fine.
- **No `DROP COLUMN` / `DROP TABLE`** in the same release that removes the
  code that uses it. Two-phase: ship code that ignores the column, wait one
  release, then drop. Same for renames (add new, dual-write, drop old).
- **`downgrade()` must `raise NotImplementedError`** — we never roll
  schemas backward; we restore from backup instead.

The Alembic chain in `backend/migrations/versions/` already follows this.
Any new revision should too — the data-preservation guard will catch
violations on deploy.

---

## Phase 4 — Backups & restore

### 4.1 What's backed up

- **Daily** at 02:30 server time (cron) → `<ts>__daily.sql.gz`
- **Pre-deploy** automatically → `<ts>__pre-deploy-<sha>.sql.gz`
- **Pre-restore** automatically → `<ts>__pre-restore-<unix>.sql.gz`
- **Manual** any time → `./scripts/vps/backup.sh "before-rzp-rotation"`

Each backup is a `pg_dump --clean --if-exists` of `cpmai_prep`, gzipped.
Sibling `.env.tar.gz` archives the env files at backup time.

### 4.2 Retention

- Daily: last 30 kept
- Pre-deploy: kept for 14 days (covers most rollback windows)
- Manual / arbitrary: kept for 30 days

### 4.3 Restore

```bash
# from the latest backup (any kind)
./scripts/vps/restore.sh latest

# from a specific file
./scripts/vps/restore.sh /var/backups/cpmai-prep/20260506T020000Z__daily.sql.gz

# unattended (CI/automation)
CONFIRM=1 ./scripts/vps/restore.sh /var/backups/.../file.sql.gz
```

`restore.sh` takes a pre-restore safety backup, drops + recreates the DB,
runs `alembic upgrade head` (in case the backup is from an older schema),
restarts backend, waits for health.

### 4.4 Off-site copies

The local `/var/backups/cpmai-prep` is on the same disk as the VPS. For
disaster-recovery, periodically pull a copy down:

```bash
# from your laptop, weekly
rsync -avh --include='*__daily.sql.gz' --exclude='*' \
  deploy@<VPS_IP>:/var/backups/cpmai-prep/ ~/cpmai-backups/
```

Or set up a cron on a *different* box. Don't put another rclone-to-S3 step
inside the VPS itself — defeats the "different blast radius" principle.

---

## Phase 5 — Logs

### 5.1 Application logs

Backend writes structured JSON to `backend/logs/app.jsonl` (mounted from
host so logs survive container restarts):

```bash
# tail user journey + audit + http (greppable)
tail -f /opt/cpmai-prep/backend/logs/app.jsonl | jq

# grep all journey events for one user
grep '"user_id":42' /opt/cpmai-prep/backend/logs/app.jsonl | jq -c
```

The logger redacts password / token / secret fields. `/auth/refresh` and
`/auth/google` request bodies are excluded from the access log.

### 5.2 Caddy access logs

```bash
tail -f /var/log/caddy/cpmaiexamprep-access.log    # apex
tail -f /var/log/caddy/api-access.log              # api subdomain
journalctl -u caddy -f                             # caddy service log
```

Caddy rotates these automatically (100 MB × 5 files per host).

### 5.3 Container logs

```bash
cd /opt/cpmai-prep
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=200 frontend
```

---

## Phase 6 — Operational tasks

### 6.1 Promote a Google user to admin

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  exec postgres psql -U cpmai -d cpmai_prep \
  -c "UPDATE users SET role='admin' WHERE email='colleague@cpmaiexamprep.com';"
```

### 6.2 Rotate Razorpay or Google secrets

```bash
./scripts/vps/backup.sh "before-secret-rotation"
sudo -u deploy nano /opt/cpmai-prep/backend/.env       # edit values
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart backend
# frontend: only restart if NEXT_PUBLIC_* changed (then full rebuild)
```

### 6.3 Add another subdomain (e.g. n8n)

Append to `/etc/caddy/Caddyfile`:

```
n8n.cpmaiexamprep.com {
    reverse_proxy localhost:5678
}
```

```bash
sudo systemctl reload caddy
```

Caddy issues the certificate on the next request.

### 6.4 Renew TLS

Caddy auto-renews. Nothing to do. To verify:

```bash
sudo journalctl -u caddy | grep -i 'certificate'
```

### 6.5 Reboot the VPS

`restart: always` on every service means the stack comes back up after
reboot. Smoke check:

```bash
curl -fs https://api.cpmaiexamprep.com/health && echo OK
```

---

## Phase 7 — Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 502 from Caddy | backend container down | `docker compose ... ps`, then `logs backend` |
| TLS issuance error | port 80 blocked or DNS not pointing here | check `ufw status`, `dig cpmaiexamprep.com` |
| Frontend serves old version after deploy | NEXT_PUBLIC_* not rebuilt | `deploy.sh` always rebuilds; if you ran a custom command, use `compose build --no-cache frontend` |
| Smoke fails on first install | DNS not propagated yet | wait + retry; the smoke uses the public URL only if you point it there |
| `pg_dump` fails | postgres container not up | `docker compose ... up -d postgres` |
| Deploy refuses to run | uncommitted changes on the VPS | `git status` — you should never edit on the VPS; deploy from main |

If you are truly stuck, the safest reset is:

```bash
./scripts/vps/restore.sh latest          # snapshot from before the breakage
./scripts/vps/deploy.sh                  # re-deploy current main
```

---

## Phase 8 — Going from test to live

1. `RAZORPAY_KEY_ID` / `_SECRET` / `_WEBHOOK_SECRET` — switch to live values
2. Activate Google OAuth (production verification status — usually not needed
   for limited-user apps under your @cpmaiexamprep.com Workspace)
3. Take a manual backup tagged `before-go-live` so you have a clean baseline
4. Update Razorpay webhook URL to the api.* hostname
5. Rotate `BOOTSTRAP_ADMIN_PASSWORD` (or change the admin password in the UI)

---

## File index

| File | Purpose |
|---|---|
| [scripts/vps/provision.sh](../scripts/vps/provision.sh)       | One-time VPS bootstrap (root) |
| [scripts/vps/install_app.sh](../scripts/vps/install_app.sh)   | First-time app install (deploy user) |
| [scripts/vps/deploy.sh](../scripts/vps/deploy.sh)             | Repeatable deploy (every change) |
| [scripts/vps/backup.sh](../scripts/vps/backup.sh)             | Manual or cron backup |
| [scripts/vps/restore.sh](../scripts/vps/restore.sh)           | Restore from any backup |
| [docker-compose.prod.yml](../docker-compose.prod.yml)         | Prod overrides (no host ports, restart: always, prod build) |
| [frontend/Dockerfile.prod](../frontend/Dockerfile.prod)       | Multi-stage Next.js prod image |
| [infra/Caddyfile](../infra/Caddyfile)                         | Reverse proxy + auto-TLS |

All scripts are **idempotent**. Run them as many times as you want.
