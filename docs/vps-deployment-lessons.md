# VPS deployment — lessons learned

Companion to [vps-deployment.md](vps-deployment.md). Captures **every hiccup
hit during the first production install on a Hostinger Ubuntu 24.04 VPS** and
the specific fix that made each one self-heal on future installs.

> **Operating principle**: every issue here was hit by hand once. Anything
> that was a one-off hack on the VPS has been ported back into git so the
> next deploy is automatic. Don't fix things on the VPS without also pushing
> the fix to source — that drift is what burned us repeatedly.

---

## Local pre-push gate

Before any code reaches GitHub Actions, a `pre-push` git hook runs the same
checks the CI test gate runs (frontend vitest, frontend build, backend pytest
if Docker is up). Catches breakages in 30s locally instead of 3 minutes after
push.

**One-time setup, per clone:**

```bash
./scripts/setup-hooks.sh
```

Sets `git config core.hooksPath .githooks` so the tracked hook fires.

**Day-to-day**: just `git push` — the hook runs automatically. If it fails,
fix and re-push. To bypass for emergencies (e.g. a doc-only push you trust
won't touch tested paths):

```bash
git push --no-verify
# or
SKIP_PREFLIGHT=1 git push
```

**Run the same checks manually any time:**

```bash
./scripts/preflight.sh                  # all
SKIP_BACKEND=1 ./scripts/preflight.sh   # frontend only (faster)
```

**Worktree-aware:** if you run preflight from a git worktree, it checks
that any running backend container is bind-mounted to *this* worktree's
`backend/` (not the parent repo's). If they don't match, it falls back to
`docker compose run --rm --no-deps --user 0:0 backend` from the worktree
dir, which mounts the worktree backend correctly and avoids port conflicts
with the parent stack. Without this check, a stale parent-repo container
would silently test the wrong code.

**Windows skip:** `next build` is skipped on Windows because `@vercel/og`
fails with `TypeError: Invalid URL` during prerender there. CI runs Linux
and catches build issues. The summary at the end labels this as deferred.

---

## Quick-reference table

Read this top-to-bottom before your next fresh-VPS deploy. Every row is
something the scripts now handle automatically, with the manual-action
column listing what's left for an operator (usually nothing, occasionally
a one-time `.deploy.conf` line).

### Hostinger / VPS-image specifics

| # | Symptom | Cause | Auto-fix | Manual action |
|---|---|---|---|---|
| 1 | `docker compose up` fails: `failed to bind host port 127.0.0.1:8000/tcp: address already in use` even though `ss -ltnp` shows 8000 free | Hostinger's image (likely `monarx-agent` on `127.0.0.1:65529`) reserves common loopback ports at the kernel level — invisible to `ss` / `lsof` / `fuser` but Docker can't bind | `docker-compose.prod.yml` interpolates `BACKEND_HOST_PORT` / `FRONTEND_HOST_PORT` from `.deploy.conf`. Caddy substitutes the upstream port too. Health probes use the configured port. | If a fresh VPS hits the bind error, add to `.deploy.conf`: `BACKEND_HOST_PORT=8001` + `FRONTEND_HOST_PORT=3001`, re-run `install_app.sh` |
| 2 | n8n / Traefik already binding ports 80/443 (Hostinger 1-click stack) | Hostinger preinstalls the n8n stack with a Traefik reverse proxy on 80/443 | `provision.sh` warns when 80/443 are occupied | One-time: `docker stop n8n-traefik-1 && docker update --restart=no n8n-traefik-1`. Keep the n8n app container itself (port 5678 loopback) |
| 3 | `PasswordAuthentication no` in `/etc/ssh/sshd_config` had no effect — `sshd -T` still showed `yes` | Ubuntu 24.04's sshd reads `Include /etc/ssh/sshd_config.d/*.conf` near the top, and Hostinger's `50-cloud-init.conf` re-enables password auth. First-match-wins, so include drops win. | Documented in [vps-deployment.md](vps-deployment.md) Phase 1.4 | Drop `00-cpmai-lockdown.conf` (prefix `00-` so it loads first) into `/etc/ssh/sshd_config.d/` with `PasswordAuthentication no`, `PermitRootLogin no`, `KbdInteractiveAuthentication no` |
| 4 | `provision.sh` "Next steps" prints an IPv6 address for DNS | `curl ifconfig.me` returns IPv6 on this VPS | Cosmetic only — DNS still uses the IPv4 from your registrar | Ignore the IPv6 line; use the public IPv4 you got from Hostinger |
| 5 | `provision.sh` warns "Port 80 or 443 in use" at the end of its run | Heuristic in the script triggers on Caddy's own listening sockets after Caddy was just installed | Cosmetic — false positive | Verify with `ss -ltnp \| grep -E ':(80\|443) '` — if only `caddy` is listed, ignore |

### Docker Compose / containers

| # | Symptom | Cause | Auto-fix | Manual action |
|---|---|---|---|---|
| 6 | Backend container's image-baked `/app/.env` masked by host's `0600` file → `PermissionError: Permission denied: '.env'` on startup | Compose **merges** per-service `volumes:` across files (not replace). Prod override's logs mount got *added* to base's `./backend:/app` source mount, which masked image content with host content | Split into canonical pattern: `docker-compose.yml` (prod-shaped base, no source mounts), `docker-compose.override.yml` (auto-loaded for dev only — adds source mounts + `--reload`), `docker-compose.prod.yml` (explicit `-f`, never auto-loads override) | None — `docker compose up` (dev) and `docker compose -f docker-compose.yml -f docker-compose.prod.yml up` (prod) both work as expected |
| 7 | Frontend's image-baked `/app/.next` masked by host's `./frontend` → `next start` says "Could not find a production build" | Same merge bug as #6 | Same split fix as #6 | Verify with `docker compose -f docker-compose.yml -f docker-compose.prod.yml config \| grep -A2 source:` — should show only `pgdata`, `init.sql`, `redis.conf`, and `./backend/logs`. **Not** `./backend` or `./frontend` |
| 8 | Postgres + Redis still exposed on `0.0.0.0:5433` / `0.0.0.0:6379` in prod | Same merge bug — `ports: []` in the override didn't drop the base's host port mappings | Same split: dev ports moved to `docker-compose.override.yml`; base has no host ports for stateful services | None — `docker compose ps` in prod shows `5432/tcp` (internal) instead of `0.0.0.0:5433->5432/tcp` |
| 9 | Backend crashloops with `PermissionError: '/app/logs/app.jsonl'` | Bind-mounted `./backend/logs` auto-created by Docker as `root:root` on first `compose up`. Container's `app` user (uid 999, from backend Dockerfile's `useradd -r -g app app`) can't write | `install_app.sh` and `deploy.sh` both pre-create `backend/logs` with `chown 999:999` before `compose up` | None |
| 10 | Docker port table out of sync — claims 8000 in use after a previous `up` failed mid-network-setup | Stale Docker network state | `deploy.sh` runs `compose down -v` followed by `up` if needed; usually a `systemctl restart docker` clears it | If port 8000 stays "in use" with nothing listening, run `sudo systemctl restart docker` once |

### Caddy / TLS

| # | Symptom | Cause | Auto-fix | Manual action |
|---|---|---|---|---|
| 11 | `systemctl reload caddy` hangs indefinitely under timeout retries | Caddy was waiting for ACME issuance to start; *real* problem was its log files at `/var/log/caddy/` couldn't be opened. `LogsDirectory=caddy` in the systemd unit had reset perms | Documented in [vps-deployment.md](vps-deployment.md). For new installs, `provision.sh` creates the log dir with right ownership | If hit: `sudo systemctl stop caddy && sudo chown -R caddy:caddy /var/log/caddy && sudo chmod 755 /var/log/caddy && sudo systemctl start caddy` |
| 12 | `/etc/caddy/Caddyfile` ends up with empty hostnames and `encode` outside any site block — Caddy refuses to start | `install_app.sh`'s sed substitution used `PROD_DOMAIN_VALUE` extracted from `ALLOWED_HOSTS` via a regex that depended on JSON quotes — but bash strips quotes when sourcing a `.env` file | `install_app.sh` now persists `PROD_DOMAIN` in a sidecar `.deploy.conf` (bash-friendly, no quote stripping) | None on fresh installs |
| 13 | After updating `BACKEND_HOST_PORT` to 8001, Caddy still proxies to `localhost:8000` and times out | Caddy was reloaded but the Caddyfile still had the old upstream port | `install_app.sh`'s Caddyfile install substitutes both domain *and* upstream ports from `.deploy.conf` | After changing `BACKEND_HOST_PORT` mid-life, manually `sudo sed -i 's/localhost:8000/localhost:8001/' /etc/caddy/Caddyfile && sudo systemctl reload caddy` |

### Backend / FastAPI

| # | Symptom | Cause | Auto-fix | Manual action |
|---|---|---|---|---|
| 14 | Health probe `curl localhost:8000/health` returns `400 Bad Request` | FastAPI `TrustedHost` middleware rejects `Host: localhost` because `ALLOWED_HOSTS` only listed the public domain triplet | `install_app.sh` and `deploy.sh` send `Host: api.<PROD_DOMAIN>` header on internal probes; smoke runs against the public URL | If you need to debug from inside the VPS without going through Caddy: `curl -H "Host: api.cpmaiexamprep.com" http://localhost:8001/health` |
| 15 | Frontend on port 3001 (after Hostinger port shift) gets "Failed to fetch" — preflight 4xx | `CORS_ORIGINS` only had `http://localhost:3000`, not `:3001` | `bootstrap.sh` writes both 3000 + 3001 by default in dev; ports come from .deploy.conf in prod | If you need a non-default port: `sed -i 's\|^CORS_ORIGINS=.*\|CORS_ORIGINS=["http://localhost:3000","http://localhost:<port>"]\|' backend/.env && docker compose restart backend` |
| 16 | `POST /exam-sets/<slug>/start` blocked by CORS preflight after Round 2 — "doesn't pass access control check: It does not have HTTP ok status" | New `X-Anon-Token` request header from the anon-attempts feature wasn't in `app/main.py`'s `allow_headers` list. Browsers refuse non-simple headers that aren't explicitly allowed | Fixed in commit `45e0bdf` — added `X-Anon-Token` to `allow_headers` | Any new custom header you add to the API client must also go in `allow_headers` in `app/main.py` |

### Frontend / Next.js build-time

| # | Symptom | Cause | Auto-fix | Manual action |
|---|---|---|---|---|
| 17 | `next build` (in Dockerfile.prod) fails on `AnnotatableText.tsx:51 — 'el' is possibly 'null'` | TypeScript closure narrowing fails: outer `if (!el) return` doesn't carry into the inner `onMouseUp` function | Re-narrow inside the closure (commit `bd31dcd`). New rule: any TS strict-null error caught only by `next build` should be added back into the source | Run `cd frontend && npm run build` locally before pushing to catch the same class of error |
| 18 | `next build` fails on `[...Set]` spread — "can only be iterated through when using --downlevelIteration flag or with a target of es2015 or higher" | `frontend/tsconfig.json` had no `target` field, so TS defaulted to ES3 | Added `"target": "es2020"` (commit `8f0dc33`). Covers Set/Map iteration, optional chaining, etc. | None |
| 19 | Prerender error: `useSearchParams() should be wrapped in a suspense boundary at page "/login"` | `next dev` skips static prerender; `next build` runs it. `useSearchParams` in a client component without a Suspense parent breaks SSR | `/login` now wraps `LoginForm` in `<Suspense fallback={...}>` (commit `14cd479`) | Any other client page using `useSearchParams` / `usePathname` needs the same wrapper |
| 20 | Prerender error: `Expected <div> to have explicit "display: flex" or "display: none" if it has more than one child node.` from `/twitter-image` | `@vercel/og` requires multi-child divs to declare flex layout. The headline div had `text + <br/> + text` (3 children) | Replaced with two stacked single-child divs in a flex column container (commit `9f7cddb`) | Any new OG image must follow the @vercel/og rules — no implicit block layout for multi-child divs |
| 21 | After mid-session code changes, dev server returns `Cannot find module './948.js'` | Stale `.next` build cache referencing chunks that no longer exist | None (dev-only) | `cd frontend && rm -rf .next && npm run dev` |
| 22 | `next build` fails locally on Windows with `TypeError: Invalid URL` from `@vercel/og` on `/twitter-image` route export | Known Vercel-OG cross-platform issue — `fileURLToPath` can't handle Windows path | None (Linux-only fix would lose the OG image) | Run prod-style builds inside Docker or on Linux. CI runs on `ubuntu-latest` and is unaffected |

### Database / Alembic / seeds

| # | Symptom | Cause | Auto-fix | Manual action |
|---|---|---|---|---|
| 23 | First-deploy `alembic upgrade head` "succeeds" through 0001 + 0002 but `0003_payment_providers` fails with `relation "users" does not exist` | `0001_baseline.py` is intentionally a `pass` — it stamps an existing schema that was originally built via `Base.metadata.create_all()`. On a fresh DB the migration chain is missing the actual table creation | Both `install_app.sh` and `deploy.sh` check for the `users` table; if missing, they run `Base.metadata.create_all()` then `alembic stamp head`. On a normal redeploy this is a detection-only no-op | None |
| 24 | New default settings or FAQs never appear on prod even after pulling the seed JSON | Idempotent seeder uses "skip if table non-empty" for FAQs/questions/exam_sets, "skip if key exists" for system_settings. But `deploy.sh`'s no-op path (when no commits diff) used to skip the seeder entirely | `deploy.sh` no-op path now runs the idempotent seeder (commit `08ef448`) so seed JSON updates land even on a SHA-equal redeploy | None |
| 25 | Empty FAQ section on landing — "No FAQs published yet" | Seeder didn't ship default FAQs | `seed_faqs()` added with 5 generic CPMAI FAQs in `faqs_default.json` (commit `08ef448`). Idempotent: only inserts when the table is empty | None |
| 26 | `/admin/settings` shows fewer keys on prod than local — landing-page CTA / upsell text not editable | Those keys auto-create on `/admin/settings` PATCH, so they only existed on local. Fresh installs never had them | All 5 `landing.*` keys added to `default_settings.json` (commit `6e736d5`). Future seeders catch any missing key | When adding a new `settings_store.get_*()` call in code, also add the row to `default_settings.json` so admins can find it in the UI without reaching for psql |
| 26b | Prod deploy fails at `alembic upgrade head` with `extension "vector" is not available` even after `docker-compose.yml` was bumped from `postgres:16-alpine` → `pgvector/pgvector:pg16` | `deploy.sh` used `up -d --no-deps backend frontend` — postgres container never gets recreated on a rolling deploy, so it's still running the OLD image. The `pgdata` volume preserved data, but the postgres binary in the container had no pgvector extension | `deploy.sh` now runs `$DC up -d postgres redis` before recreating backend/frontend. Compose detects image drift and recreates only when needed; on a normal redeploy this is a no-op (no downtime) | One-time recovery when first hit: `$DC pull postgres && $DC up -d --force-recreate --no-deps postgres`, then re-run the deploy. pgvector/pgvector image is binary-compatible with postgres:16 — pgdata volume survives |
| 26c | Prod deploy fails at `alembic upgrade head` with `psycopg2.errors.UnsafeNewEnumValueUsage: unsafe use of new value "landing_hero" of enum type leadsource ... New enum values must be committed before they can be used` | Alembic's `env.py` wrapped EVERY pending migration in a SINGLE outer transaction. When two consecutive migrations both touch an enum (0016 added the lowercase values, 0017 ran `UPDATE leads SET source = lower(source::text)::leadsource`), the `ALTER TYPE ADD VALUE` and the cast-using-that-value shared a transaction — which Postgres specifically forbids. The CI alembic-from-empty gate passed by luck (empty `leads` table → UPDATE matched 0 rows → cast never executed). Prod had a row → prod failed. Auto-rollback fired and restored cleanly | `migrations/env.py` now sets `transaction_per_migration=True` in `context.configure()`. Each migration gets its own COMMIT, so a new enum value is visible before the next migration tries to use it. Also strengthened the `migration-drift` CI gate with a "regression — uppercase leadsource row survives full chain" step that applies migrations through 0015, inserts a row with the uppercase NAME via raw SQL, then runs the rest of the chain | None — auto-rollback restored prod before any user-visible damage |

### Auth / credentials

| # | Symptom | Cause | Auto-fix | Manual action |
|---|---|---|---|---|
| 27 | After admin rotates their password via `/admin/users → Reset password`, the next `deploy.sh` fails at smoke with `[FAIL] login as super-admin status=401 invalid_credentials` | Smoke read `BOOTSTRAP_ADMIN_PASSWORD` from `.env` — stale once the operator rotated their password | New dedicated `SMOKE_ADMIN_*` super-admin (commit `45918ed`); seeder syncs the DB hash with the `.env` value on every deploy. Operator rotation never affects smoke | None on fresh installs (auto-generated). On existing installs, `deploy.sh` backfills `SMOKE_ADMIN_*` automatically the first time it sees the gap |
| 28 | `BOOTSTRAP_ADMIN_PASSWORD` is in plaintext in `backend/.env` | By design — env files at mode `0600`, gitignored, never logged. After install, rotate via UI; the env value is no longer used | None — accepted threat model | Treat `backend/.env` like a password manager file. Never paste in chats. Rotate `BOOTSTRAP_ADMIN_PASSWORD` after first install via `/admin/users` |
| 29 | `chmod 0600` on env files makes container's `app` user (uid 999) unable to read them | Host file owner is `deploy` (uid 1000); container's user is uid 999 — different uids, mode 0600 lets only owner read | Switched to mode `0644` on env files; perimeter (ufw, single-user VPS) is what actually protects | None |
| 30 | First-ever deploy fails at `pre-deploy backup failed — refusing to proceed` even though SQL + env tar succeeded | `backup.sh` retention prune used `ls -1t *__daily.sql.gz \| tail -n +31 \| xargs rm` — under `set -euo pipefail` an empty pattern (no matching files yet) is exit-1 → script aborts | Wrapped retention pass in a `set +e` subshell (commit `7dc6253`) | None |

### Deploy.sh script timing & flow

| # | Symptom | Cause | Auto-fix | Manual action |
|---|---|---|---|---|
| 31 | Manually running `git pull` *before* `deploy.sh` makes the script take the no-op path — skips backup, build, migrations, restart | `deploy.sh` captures `START_SHA` at script entry, then pulls. If pre-pulled, START==NEW → no-op branch | No-op branch now runs idempotent seeder + smoke (so seed-only changes still land) | **Rule of thumb**: never `git pull` before `deploy.sh`. Let the script do its own pull |
| 32 | Bug fixes to `deploy.sh` itself don't take effect on the run that pulls them | Bash interprets script line-by-line as it reads. `git pull` updates the file on disk but the running interpreter has already loaded the body. New code lands on the *next* run | Critical paths inside deploy.sh that depend on each other now self-restart (e.g. `SMOKE_ADMIN_*` backfill restarts backend before reaching the seeder) | If you push a critical deploy.sh fix and a deploy is mid-flight, run deploy.sh once more after the pull |
| 33 | `set -e + pipefail` in scripts swallows errors silently and aborts mid-run with no obvious banner | Whole script class of pitfall — any pipeline that returns non-zero on a benign condition (empty pattern, etc.) kills everything | Non-critical steps (cron install, retention prune) wrapped in `\|\| true` or subshells with `set +e` | When writing new bash, default to `set -euo pipefail` AND wrap optional steps with `\|\| warn "…"` |
| 34 | Existing untracked working-tree files block `git pull --ff-only` ("would be overwritten by merge") | Worktree drift from earlier session — files created locally before being committed upstream | None — operator decision | `rm` the listed files (they're identical to what git is bringing in), then re-pull. Or `git stash --include-untracked` then pop |
| 35 | A failed deploy leaves the site stuck on the new backend image expecting tables the failed migration never added (e.g. `column "daily_chat_limit_override" does not exist` on every login) | `deploy.sh` historically had no failure-recovery path — it just `exit 1`-ed on alembic failure, leaving the half-applied state visible to users | `deploy.sh` now tags the pre-build backend/frontend images as `:previous` and arms an ERR/explicit-die trap that, on any failure between build and smoke-pass, (a) retags `:previous` → `:latest`, (b) recreates backend + frontend on the previous images, (c) `restore.sh`'s the DB from the pre-deploy backup, (d) git-resets working tree to `START_SHA`, (e) restarts backend, (f) verifies `/health`. Escape hatch: `SKIP_ROLLBACK=1 ./scripts/vps/deploy.sh` to debug a failure in place | None on the happy path. If auto-rollback itself can't bring `/health` back up, the script prints `check: $DC logs backend` and exits 1 — investigate from there |
| 36 | Deploy fails at the very first step with `fatal: unable to access 'https://github.com/...': GnuTLS recv error` or `Failed to connect to github.com port 443 after Xms` — repeatedly enough to be annoying but transiently | Hostinger → github.com HTTPS has occasional 1-2 minute reachability glitches at the network level (upstream provider routing, TLS handshake timeouts). Each glitch bounced a deploy that had nothing wrong with it, forcing a manual "Re-run failed jobs" from the GH Actions UI | `deploy.sh` retries `git fetch --prune origin` up to 3 times with 10s backoff before giving up. The ff-only check on the second line is NOT retried — non-FF history / uncommitted changes are operator-fixable, not network-blip-fixable | If all three retries fail, the network outage is genuine. SSH to the VPS, `curl -v https://github.com` to confirm, then either wait it out or contact Hostinger support. Prod is unaffected because the failure is before any state change |

### Smoke vs. real browser

| # | Symptom | Cause | Auto-fix | Manual action |
|---|---|---|---|---|
| 35 | Smoke green but browser hits "Failed to fetch" on the same endpoints | `curl` (used by smoke) ignores CORS. Only real browsers enforce it. CORS misconfig (#16) only surfaced in browser | Documented as a follow-up gap — manual browser-flow probe in the test plan | After every release that adds a new API request header or origin, do a quick incognito-window check on the public URL |
| 36 | Admin "Test" button on a Razorpay payment provider says `✗ razorpay package not installed` even after a clean rebuild | razorpay 1.4.2's `client.py` does `import pkg_resources`. setuptools 80 dropped that module. RazorpayProvider's catch-block was rewriting the real `ModuleNotFoundError` into a misleading "package not installed" string | `requirements.txt` pins `setuptools<80`. RazorpayProvider error message now surfaces the real `ImportError` class + message instead of a fixed-string. Unit test (`test_razorpay_sdk_imports.py`) catches a future regression on first install | None on next deploy — the rebuilt image picks up the pin |
| 37 | Disk fills over time with orphaned `cpmai-prep-backend` / `cpmai-prep-frontend` images (each ~500 MB) | Each `docker compose build` overwrites the `:latest` tag and leaves the previous image dangling. Without explicit cleanup, every deploy keeps a copy | `deploy.sh` ends with `docker image prune -af --filter "until=168h"` + `docker builder prune -af --filter "until=168h"`. 7-day retention preserves a manual-rollback target | If disk pressure spikes between deploys, run `docker system df` to see what's consuming space; one-shot cleanup with `docker image prune -af` (drops the retention window) |

---

## Hostinger-specific tweaks (concentrated)

For a fresh Hostinger Ubuntu 24.04 VPS with the n8n 1-click stack, the
operator-side actions are **only**:

```bash
# 1. As root, before running provision.sh: stop n8n's traefik container
docker stop n8n-traefik-1
docker update --restart=no n8n-traefik-1

# 2. After provision.sh, lock down SSH against Hostinger's cloud-init override
sudo tee /etc/ssh/sshd_config.d/00-cpmai-lockdown.conf > /dev/null <<'EOF'
PasswordAuthentication no
PermitRootLogin no
KbdInteractiveAuthentication no
EOF
sudo systemctl reload ssh

# 3. Before install_app.sh, if the bind-port test fails, add to .deploy.conf:
echo 'BACKEND_HOST_PORT=8001'  >> /opt/cpmai-prep/.deploy.conf
echo 'FRONTEND_HOST_PORT=3001' >> /opt/cpmai-prep/.deploy.conf
```

Everything else is handled by the scripts on first run.

---

## Local dev workflow stays unchanged

The whole point of these fixes is that they live in the **prod path only**.
Local dev workflow on your laptop is unchanged:

```bash
./scripts/bootstrap.sh                     # first-time setup
./scripts/upgrade.sh                       # subsequent code pulls (migration + seed + smoke)
docker compose up                          # daily start (loads override.yml automatically)
```

The VPS-specific bits (port shifts, log dir chown, schema bootstrap, public-URL
smoke, smoke admin separation) only fire when you're running with `-f
docker-compose.prod.yml`. If you ever see something on the VPS that's different
from what local dev does, the answer is **never** to modify behavior locally —
find the prod-only path that needs to handle it (typically in
`scripts/vps/*.sh` or the prod compose override).

---

## File index of the prod path

| File | When it runs | What it does |
|---|---|---|
| `scripts/vps/provision.sh` | Once, as root, on a fresh VPS | Install Docker + Caddy + ufw + fail2ban; create `deploy` user with NOPASSWD sudo |
| `scripts/vps/install_app.sh` | Once, as deploy, after provision | First-time app install: prompts → env files (incl. `SMOKE_ADMIN_*`) → Caddyfile → build → schema bootstrap → seeds → cron → smoke |
| `scripts/vps/deploy.sh` | Every deploy | git pull → backup → schema-bootstrap-if-fresh → build → migrate → seed → restart → data guard → smoke |
| `scripts/vps/backup.sh` | Daily cron + pre-deploy | pg_dump + .env tar → `/var/backups/cpmai-prep/` |
| `scripts/vps/restore.sh` | Manual rollback | Drop DB + restore from gzip dump (with pre-restore safety snapshot) |
| `.deploy.conf` (gitignored) | Read by install/deploy | `PROD_DOMAIN`, `BACKEND_HOST_PORT`, `FRONTEND_HOST_PORT` — VPS-specific tunables |
| `backend/.env` (gitignored, 0644 on VPS) | Read by backend container + smoke | App secrets, BOOTSTRAP_ADMIN_*, SMOKE_ADMIN_* |
| `docker-compose.yml` (tracked) | Both paths (base) | postgres + redis + service skeletons, prod-shaped (no source mounts, no host ports) |
| `docker-compose.override.yml` (tracked) | Auto-loaded by `docker compose up` (no `-f`) | Dev source mounts, dev ports, `--reload`, `npm run dev` |
| `docker-compose.prod.yml` (tracked) | Explicit `-f` only | restart:always, loopback ports, prod build args, no source mounts |
| `infra/Caddyfile` (tracked) | Template; install_app.sh substitutes domain + ports | Reverse proxy + auto-TLS |

---

## One-time VPS image cleanup

`deploy.sh` auto-prunes dangling images older than 7 days at the end of
every **successful** deploy. If a deploy fails before that step (as
happened during the two May rollback incidents), images accumulate.
After a string of failed deploys, `/var/lib/docker` can grow noticeably
— symptoms include slower builds and, eventually, a disk-full deploy
abort.

Run on the VPS as the `deploy` user (sudo not required — the user is
already in the `docker` group):

```bash
docker system df -v          # before — see what's reclaimable
docker image prune -af        # remove unused images (running ones stay)
docker builder prune -af      # reclaim build cache layers
docker system df -v           # after — sanity check
```

**Safe to run any time.** Won't touch:

- Running containers or the images they're built from.
- `cpmai-prep-backend:previous` / `cpmai-prep-frontend:previous` —
  referenced by `deploy.sh`'s auto-rollback path, so they count as
  "in use" until a future successful deploy replaces them.
- Named volumes (postgres data, etc.) — `image prune` only touches
  images, not volumes.

If you ever need to reclaim volume space too (you usually don't):
inspect first with `docker volume ls` + `docker volume inspect`. Never
`docker volume prune` on the prod host without a fresh DB backup.

## 37. GeoIP: license key rotation never requires a deploy

**Date:** 2026-05-13.
**Status:** New invariant, pinning the design.

The MaxMind license key for GeoIP enrichment lives in
`system_settings` (key: `geoip.maxmind_license_key`, `is_secret=true`),
NOT in `backend/.env`. Rotating it is an admin-UI action:

1. Generate new key at maxmind.com → My License Keys.
2. Revoke the old one.
3. /admin/geoip → license key card → "Rotate" → paste new value.
4. Click "Test connection". If green, you're done.
5. Optional: click "Refresh now" to download a fresh DB with the new
   credentials immediately, otherwise wait for the next scheduled
   cron run (twice weekly — Wed + Sat 04:17 UTC).

**Do NOT** put the license key in `backend/.env` or anywhere on the
filesystem. The settings table is the single source of truth, the
cron reads it via `python -m app.services.geoip refresh`, and the
admin UI rotates it.

**Bind-mount sanity:** the GeoIP database lives on the host at
`/srv/cpmai/geoip/` and is bind-mounted into the backend container at
the same path. `deploy.sh` ensures the directory exists with uid 999
ownership on every deploy. If the bind mount is missing from
`docker-compose.prod.yml`, the refresh CLI will write to a container-
local path that disappears on next `compose up` — and you'll see
"database_present: false" in /health after every deploy. Fix is to
add the mount, not to symlink.

**Failure modes ranked by frequency:**

- `401` from MaxMind → license key revoked or wrong (operator rotated
  at maxmind.com without updating /admin/geoip).
- `network` error → VPS → download.maxmind.com is blocked or the CDN
  edge is degraded. Wait, retry. The cron script's `set -e + tee` makes
  these visible in `/var/log/cpmai/geoip_refresh.log`.
- `database_present=false` after a deploy → bind mount missing (above).
- `database_age_days > 35` (stale) → cron didn't run for a long time.
  Check crontab (`crontab -l | grep geoip`) and the cron log
  (`/var/log/cpmai/geoip_refresh.log`). With twice-weekly cron, 35 days
  stale = at least 8 missed runs; this is a real outage of either the
  cron, the network, or the MaxMind credentials, not a one-off blip.

**The schedule:** Wednesdays + Saturdays at 04:17 UTC, NOT monthly.
MaxMind releases GeoLite2 twice weekly (Tue + Fri), so a monthly cron
would leave us 0–35 days stale. The twice-weekly schedule catches each
release within 6–14 hours. The conditional-GET via If-Modified-Since
means the 6 of 8 monthly invocations that hit unchanged data return
304 in milliseconds with no download — so this is essentially free.
See `scripts/vps/install_geoip_cron.sh` for the rationale + how to
tune the schedule.

**What if MaxMind has an extended outage:** set
`geoip.refresh_enabled = false` in /admin/settings. The cron will
detect this and exit cleanly without making the call (no log spam, no
false-positive alerts). Re-enable when MaxMind is back.

**The fail-open invariant:** GeoIP enrichment NEVER blocks the lead
capture request path. If the mmdb is missing, the lookup returns None
and the lead row stores NULL country/city — but the insert succeeds.
Same for any internal error (corrupt file, transient I/O). The whole
package is fail-open by design. See
`app/services/geoip/lookup.py:lookup()` for the catch-all.

## 38. MaxMind auth: license_key as query param, NOT HTTP basic

**Date:** 2026-05-13.
**Status:** New invariant. Re-introducing basic auth re-opens the
PR-A hotfix bug.

The public direct-download URL is
`https://download.maxmind.com/app/geoip_download?edition_id=…&license_key=…&suffix=tar.gz`.
MaxMind's own docs and the `geoipupdate` CLI ship with this shape.
Both `refresh.py` and the `/admin/geoip/test-key` endpoint MUST send
the license key as the `license_key` query param, never as
`Authorization: Basic base64(account_id:license_key)`.

MaxMind's `/app/geoip_download` endpoint technically accepts HTTP
basic auth too, but:

- The query-param form is what an operator can paste into a curl for
  ad-hoc debugging.
- The basic-auth form requires sending `account_id` as the username,
  which is metadata not strictly required for the request — adds a
  source of misconfiguration ("you sent the wrong account_id with the
  right key" failures).
- Logs of failing requests show the URL plainly; basic-auth credentials
  are buried in headers and harder to grep.

`account_id` is still STORED in the settings table for documentation
+ potential future adoption of `geoipupdate`. But neither refresh nor
test-key consult it. `credentials_configured` in the StatusReport is
True iff just the license_key is set.

There's a pytest regression guard at
`tests/unit/geoip/test_refresh.py::test_refresh_sends_license_key_as_query_param_not_basic_auth`
that fails CI if anyone reintroduces basic auth.

## 40. User deletion is ALWAYS soft, never hard

**Date:** 2026-05-13. **Status:** Invariant.

Both `DELETE /users/me` (GDPR self-service) and
`DELETE /admin/users/{id}` (admin junk-account cleanup) MUST go
through `app.services.user_deletion.soft_delete_user`. A hard delete
on a `users` row will fail because no model-level cascades are
configured for the FKs pointing at it (audit_logs, payments,
journey_events, leads.converted_user_id, etc.) — and even if cascades
WERE configured, hard-delete would wipe rows we're legally required
to keep (Indian tax law: 7-year retention on financial records).

A regression that re-introduced hard delete would surface as a
generic 409 "This change conflicts with existing data — most often
a unique field…" (our IntegrityError catch-all in `app/main.py`). The
operator wouldn't get any clear signal about what failed.

Pinned by `tests/integration/test_admin_user_delete.py`:
* `test_admin_delete_user_soft_deletes_and_succeeds`
* `test_admin_delete_preserves_fk_referencing_rows`
* `test_admin_delete_post_delete_login_is_blocked`

The soft-delete contract (`app/services/user_deletion.py`):
* `email → "deleted-{id}@redacted.invalid"`
* `name, password_hash, google_id → NULL`
* `is_active → False` (blocks login)
* `deleted_at → now()`
* Idempotent: re-deleting a soft-deleted user is a no-op (returns
  False from the service function; the audit log records
  `was_already_deleted: True`).

Related: `UserOut.email` is typed `str`, NOT `EmailStr`. Pydantic's
`EmailStr` rejects RFC 2606 reserved domains (`.invalid`), so a
strict-typed output schema would 500 when serializing a soft-deleted
user. Validation belongs at input time (SignupIn / LoginIn use
EmailStr); serialization should round-trip cleanly.

**Re-login after delete is intentionally allowed — soft-delete is
NOT a ban-list.** When a soft-deleted user clicks "Sign in with
Google" again, the provisioner's lookup misses on both `google_id`
(now NULL) and `email` (now `deleted-X@redacted.invalid`), falls
through to "create new user", and they get a fresh account row with
a different `user.id`. This is intentional — it's the GDPR "right
to be forgotten" semantics: the old account is genuinely gone, the
person can come back as a fresh user. The old row is untouched.

If we ever want admin-delete to mean "ban this signup from coming
back" (e.g. for repeat spammers), we'd have to keep `google_id` and
a hash of the original email on the deleted row so the provisioner
finds it and trips `is_active=False`. That's a product decision, not
a refactor — pinned by `tests/integration/test_google_relogin_after_delete.py`
so it can't change silently.

## 39. GeoIP cron auto-installs via deploy.sh — no SSH needed

**Date:** 2026-05-13.

Previously, after a fresh deploy of the GeoIP feature, the operator
had to SSH in and run `./scripts/vps/install_geoip_cron.sh` to wire
up the every-minute refresh tick. Easy to forget; if forgotten, the
admin UI would let you configure schedule + credentials, but the
refresh would never fire on its own.

`deploy.sh` now calls `install_geoip_cron.sh` on every deploy. The
cron-installer script is idempotent (strips any existing
`geoip_refresh.sh` crontab line and re-adds the canonical one), so
re-running on every deploy is the same as "make sure the entry is
correct after any path change".

Operationally this means: merge the PR → CI deploys → cron is live →
admin opens /admin/geoip → sets license key → clicks Install database
now → done. No terminal access at any step.
