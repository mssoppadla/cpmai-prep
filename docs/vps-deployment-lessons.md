# VPS deployment — lessons learned

Companion to [vps-deployment.md](vps-deployment.md). Captures the **specific
issues we hit during the first production install** and how the scripts now
prevent them. Read this if a new deploy fails for a reason that doesn't seem
to match the runbook — odds are it's listed below.

> Operating principle: every issue here was hit by hand once. Anything that
> was a one-off hack on the VPS has been ported back into git so the next
> deploy is automatic. Don't fix things on the VPS without also pushing the
> fix to source — that drift is what burned us.

---

## 1. Hostinger-style port collisions on `127.0.0.1:8000` and `127.0.0.1:3000`

**Symptom**: `docker compose up -d` fails with
`failed to bind host port 127.0.0.1:8000/tcp: address already in use` even
though `ss -ltnp | grep ':8000 '` shows nothing listening.

**Cause**: Hostinger's default Ubuntu image has something (likely the
`monarx-agent` running on `127.0.0.1:65529`) that reserves certain common
loopback ports at the kernel level. `ss` and `lsof` don't see it but Docker
can't bind it.

**Fix in scripts**: `BACKEND_HOST_PORT` and `FRONTEND_HOST_PORT` are
configurable via `.deploy.conf`. `docker-compose.prod.yml` interpolates
them, `install_app.sh` substitutes the upstream port in the Caddyfile, and
`deploy.sh` uses them for health probes.

**On a fresh VPS hit by this**:

```bash
# After the first install fails on the bind:
nano /opt/cpmai-prep/.deploy.conf
# add:
#   BACKEND_HOST_PORT=8001
#   FRONTEND_HOST_PORT=3001

./scripts/vps/install_app.sh    # re-run; it's idempotent
```

The Caddyfile templating in `install_app.sh` will use those values; nothing
public-facing changes (Caddy still listens on 443).

---

## 2. `set -e` in shell scripts hides the real failure

**Symptom**: Script exits silently mid-step, no error message, rollback
opportunities lost.

**Cause we hit**: The cron-install block in `install_app.sh` ran `sudo
touch /var/log/...` which transient-failed under `set -e`, and the script
bailed out *before* the smoke test, which would have surfaced the actual
problem.

**Fix in scripts**: cron install is wrapped in `{ ... } || warn "..."` so a
hiccup doesn't kill the install. The script keeps going and finishes the
smoke. Same pattern for any "nice-to-have" step that shouldn't be a deploy
gate.

**Rule of thumb**: under `set -e`, every line is a kill switch. Wrap
non-critical steps in `|| warn`.

---

## 3. Docker Compose volume merge across files

**Symptom**: Production containers behave like dev (source bind-mounted
over the image's `/app`, frontend can't find `/app/.next`, backend's
image-baked `.env` is masked by host's 0600 file → `Permission denied`).

**Cause**: For `volumes:` and `ports:`, `docker compose -f base.yml -f
prod.yml` MERGES the lists across files, it doesn't replace them. So the
prod override's `volumes: [./backend/logs:/app/logs]` was being added to
the base's `./backend:/app`, not replacing it.

**Fix in scripts**: split into the canonical Compose pattern:
- `docker-compose.yml` — prod-shaped base (no source mounts, no host ports)
- `docker-compose.override.yml` — dev defaults, **auto-loaded only** by
  `docker compose up` (no `-f`). Adds source mounts + dev commands.
- `docker-compose.prod.yml` — explicit `-f` invocation, bypasses the
  override file. Adds prod-only fields.

**Verify on any VPS** before launch:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config \
  | grep -A2 'source:'
```

Expected sources: only `pgdata` (named volume), `init.sql`, `redis.conf`,
and `./backend/logs`. **NOT** `./backend` or `./frontend` — those are dev
mounts and should not appear in prod's resolved config.

---

## 4. FastAPI TrustedHost middleware rejects `localhost`

**Symptom**: Backend health endpoint returns 400 Bad Request when curled
from the host (`curl http://localhost:8000/health`). Caddy via the public
hostname returns 200 fine.

**Cause**: `ALLOWED_HOSTS` only contains `cpmaiexamprep.com`,
`www.cpmaiexamprep.com`, `api.cpmaiexamprep.com`. A request with Host
header `localhost:8000` fails the trusted-host check.

**Fix in scripts**: `install_app.sh`'s health probe sends
`-H "Host: api.<PROD_DOMAIN>"`, and the smoke test runs against the public
URL. The internal `localhost` route is no longer in the hot path.

**If you need to debug from inside the VPS** without going through Caddy:

```bash
curl -H "Host: api.cpmaiexamprep.com" http://localhost:8001/health
```

…or just hit the public URL — Caddy's localhost-only loopback is fast.

---

## 5. Bind-mounted log dir auto-created as root

**Symptom**: Backend container crash-loops with
`PermissionError: [Errno 13] Permission denied: '/app/logs/app.jsonl'`.

**Cause**: When `docker compose up` finds a missing host directory in a
bind-mount declaration, it creates the dir as `root:root` mode `755`. The
container's `app` user (uid 999, from the backend Dockerfile) can't write
to it.

**Fix in scripts**: `install_app.sh` and `deploy.sh` both pre-create the
log dir with the right ownership before `compose up`:

```bash
mkdir -p backend/logs
sudo chown 999:999 backend/logs
sudo chmod 0755 backend/logs
```

`999` is the uid created by `useradd -r -g app app` in
`backend/Dockerfile`. If you ever change that line, remember to update the
chown here.

---

## 6. Alembic baseline migration is intentionally a no-op

**Symptom**: On a fresh DB, `alembic upgrade head` "succeeds" through
`0001_baseline` and `0002_v4` but then `0003_payment_providers` fails with
`relation "users" does not exist`.

**Cause**: Early-dev workflow built the schema via
`Base.metadata.create_all()`, then introduced alembic later as a stamp on
top. So `0001_baseline.py` is an empty `pass`, not an actual schema
migration — it assumes the schema is already there.

**Fix in scripts**: Both `install_app.sh` and `deploy.sh` now check for
the `users` table before running alembic. If it's missing, they:
1. Run `Base.metadata.create_all()` to build the schema from models
2. Stamp alembic to head
3. Skip `alembic upgrade` (no-op anyway since head is the stamped version)

On a normal redeploy with an existing schema, this is a no-op detection
and `alembic upgrade head` runs as usual.

---

## 7. Bash strips quotes from JSON-shaped env vars

**Symptom**: A first version of `install_app.sh` extracted `PROD_DOMAIN`
from `ALLOWED_HOSTS` via a regex looking for quoted strings. After
`set -a; . backend/.env`, the quotes were gone and the regex matched
nothing → empty domain → broken Caddyfile and broken frontend env.

**Fix in scripts**: `PROD_DOMAIN` (and the host-port overrides) are
persisted in a separate `.deploy.conf` sidecar that's bash-friendly (no
JSON, no quotes to strip). Sourced cleanly on every run.

---

## 8. Next.js prerender errors only show on `next build`

**Symptom**: `npm run dev` (local) is happy. `npm run build` in the prod
Dockerfile fails on TypeScript strict-null narrowing
(`AnnotatableText.tsx:51 'el' is possibly 'null'`), missing tsconfig
`target` (`Set` spread can't be iterated), and prerender errors
(`useSearchParams() should be wrapped in a suspense boundary`).

**Cause**: `next dev` skips both type-check and prerender phases. They
only run during production build.

**Prevention**: before any push to main, run `cd frontend && npm run build`
locally. Catches all of the above in 30s. The CI workflow at
[.github/workflows/deploy.yml](../.github/workflows/deploy.yml) also runs
this strictly — once that's wired up, the test gate prevents bad pushes
from reaching the VPS at all.

---

## 9. SSH lockdown via `/etc/ssh/sshd_config.d/`

**Symptom**: Editing `/etc/ssh/sshd_config` to set
`PasswordAuthentication no` had no effect — `sshd -T` still showed `yes`.

**Cause**: Ubuntu 24.04's sshd reads `Include
/etc/ssh/sshd_config.d/*.conf` near the top, and Hostinger's
`50-cloud-init.conf` sets `PasswordAuthentication yes`. With sshd's
"first match wins" rule, the include wins over the main config.

**Fix**: Drop our hardening into `/etc/ssh/sshd_config.d/00-cpmai-lockdown.conf`
(prefix `00-` so it's read first):

```
PasswordAuthentication no
PermitRootLogin no
KbdInteractiveAuthentication no
```

Then `sshd -t && systemctl reload ssh`. Verify with `sshd -T | grep -iE
'^(passwordauth|permitrootlogin|kbd)'` — all three should be `no`.

This is one-time provisioning, not in any recurring script.

---

## 10. Local dev still works unchanged

The whole point of all these fixes is that they live in the prod path
only. Local dev workflow on your laptop is unchanged:

```bash
./scripts/bootstrap.sh                    # first time
./scripts/upgrade.sh                      # subsequent
docker compose up                          # daily start (loads override.yml)
```

The VPS-specific bits (port shifts, log dir chown, schema bootstrap, public-URL
smoke) only fire when you're running with `-f docker-compose.prod.yml`.

If you ever see something on the VPS that's different from what local dev
does, the answer is **not** to modify behavior locally — find the prod-only
path that needs to handle it (typically in `scripts/vps/*.sh` or the prod
compose override).

---

## File index of the prod path

| File | When it runs | What it does |
|---|---|---|
| `scripts/vps/provision.sh` | Once, as root, on a fresh VPS | Install Docker + Caddy + ufw + fail2ban; create `deploy` user |
| `scripts/vps/install_app.sh` | Once, as deploy, after provision | First-time app install: prompts → env files → Caddyfile → build → schema → seeds → cron → smoke |
| `scripts/vps/deploy.sh` | Every deploy | git pull → backup → build → migrate → restart → data guard → smoke |
| `scripts/vps/backup.sh` | Daily cron + pre-deploy | pg_dump + .env tar → `/var/backups/cpmai-prep/` |
| `scripts/vps/restore.sh` | Manual rollback | Drop DB + restore from gzip dump |
| `.deploy.conf` | Read by install/deploy | `PROD_DOMAIN`, `BACKEND_HOST_PORT`, `FRONTEND_HOST_PORT` — VPS-specific tunables |
| `docker-compose.prod.yml` | Explicit `-f` only | restart:always, loopback ports, prod build args, no source mounts |
| `docker-compose.override.yml` | Auto-loaded by `docker compose up` (no `-f`) | Dev source mounts, dev ports, `--reload`, `npm run dev` |
| `docker-compose.yml` | Both paths (base) | postgres + redis, build skeletons, prod-shaped commands |
| `infra/Caddyfile` | Template; install_app.sh substitutes domain + ports | Reverse proxy + auto-TLS |
