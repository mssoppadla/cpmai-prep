# CI/CD setup — automated promotion to production

One-time setup for the `.github/workflows/deploy.yml` pipeline. After this,
every push to `main` runs the test gate, waits for your approval, then
SSHes into the VPS and runs `./scripts/vps/deploy.sh`.

> **Prerequisite:** the VPS must already be set up via
> [vps-deployment.md](vps-deployment.md) — `provision.sh` and
> `install_app.sh` must have run successfully at least once. The CI/CD
> only handles **subsequent** deploys.

---

## What you'll set up (one-time, ~10 minutes)

1. Generate a dedicated SSH keypair on your laptop (different from your
   personal SSH key — this one is *only* for GitHub Actions).
2. Add the public key to the VPS `deploy` user's `authorized_keys`.
3. Create a GitHub Environment named **`production`** with you as the
   required reviewer.
4. Add four secrets to that environment.
5. Push a commit to `main` and click "Approve" when prompted.

---

## 1. Generate a dedicated CI deploy key

On your laptop:

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" \
  -f ~/.ssh/cpmai_deploy_ci -N ""
```

This creates two files:

- `~/.ssh/cpmai_deploy_ci`     — **private** key (goes in a GitHub secret)
- `~/.ssh/cpmai_deploy_ci.pub` — **public** key (goes on the VPS)

`-N ""` makes it passphrase-less so the runner can use it non-interactively.
This key has only one purpose (CI deploys), so the blast radius is just the
deploy user — *not* an admin/root key.

## 2. Authorize the key on the VPS

```bash
# from your laptop
ssh-copy-id -i ~/.ssh/cpmai_deploy_ci.pub deploy@<VPS_IP>

# OR manually:
cat ~/.ssh/cpmai_deploy_ci.pub | ssh deploy@<VPS_IP> \
    'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

Verify:

```bash
ssh -i ~/.ssh/cpmai_deploy_ci deploy@<VPS_IP> 'whoami && hostname'
# expected: deploy <hostname>
```

## 3. Capture the VPS host key (host-key pinning)

This makes the runner refuse to connect if the VPS's host key ever changes
unexpectedly (MITM defense). Run this from your laptop after you've SSHed
in once and trust the host:

```bash
ssh-keyscan -H <VPS_IP> 2>/dev/null
```

Copy the entire output — you'll paste it into `VPS_HOST_KEY` in step 5.

## 4. Create the `production` GitHub Environment

In GitHub:

1. Go to **Settings → Environments → New environment**
2. Name: `production`
3. Configure:
   - **Required reviewers** → add yourself (or a teammate). This is the
     approval gate — every deploy waits here.
   - **Wait timer** → optional; 5 minutes gives you a window to cancel an
     accidental push before it ever reaches production. I recommend `0`
     for now and revisit later.
   - **Deployment branches and tags** → "Selected branches and tags" →
     add rule for `main` only. This prevents anyone from accidentally
     deploying a feature branch.

## 5. Add four secrets to the environment

Still on the `production` environment page → **Environment secrets**:

| Secret name      | Value |
|---|---|
| `VPS_HOST`       | Your VPS IP or hostname (no `http://`, no port) |
| `VPS_USER`       | `deploy` (or whatever you set as `DEPLOY_USER` in `provision.sh`) |
| `VPS_SSH_KEY`    | Full contents of `~/.ssh/cpmai_deploy_ci` (the **private** key, including `-----BEGIN OPENSSH PRIVATE KEY-----` lines) |
| `VPS_HOST_KEY`   | Output of `ssh-keyscan -H <VPS_IP>` from step 3 |

> Use **Environment** secrets (scoped to `production`), not **Repository**
> secrets. Environment secrets are only available to jobs that target the
> environment — and the approval gate runs *before* those secrets are
> exposed. Repository secrets would be available to any workflow.

## 6. Trigger the first deploy

Push something tiny — a comment, a doc tweak — to `main`:

```bash
git commit --allow-empty -m "ci: smoke-test deploy workflow"
git push origin main
```

Then in the GitHub UI:

1. **Actions** tab → "deploy" workflow → click your run
2. The `test` job runs first (~3–5 min). It must go green.
3. Once it does, you'll see "Review pending deployments" — click **Approve**
4. The `deploy` job SSHes in, runs `deploy.sh`, and shows live output

If anything fails, the workflow stops there. The pre-deploy backup that
`deploy.sh` takes (right at the top, before any change) is your rollback
target. Restore from the VPS:

```bash
ssh deploy@<VPS_IP>
cd /opt/cpmai-prep
./scripts/vps/restore.sh latest
```

---

## How it ties into the existing CI

| Workflow | Trigger | Purpose | Strict? |
|---|---|---|---|
| `backend-ci.yml`  | PR + push (paths: backend/**)  | Early signal for backend changes | Permissive (`\|\| true`) |
| `frontend-ci.yml` | PR + push (paths: frontend/**) | Early signal for frontend changes | Permissive (`\|\| true`) |
| `security-scan.yml` | PR + push | pip-audit, npm audit, gitleaks | Permissive |
| **`deploy.yml`** (this one) | **push to main + manual** | **Strict test gate + production deploy** | **Strict** |

The first three are quality-of-life feedback while you're developing.
`deploy.yml` is the gate that actually ships — it re-runs the tests
strictly, in a clean environment, against a real Postgres + Redis. If
your PR-time CI was flaky-passing, `deploy.yml` will catch it.

---

## Day-to-day flow once set up

1. Develop locally → run `python scripts/smoke_admin_crud.py` against your
   local stack until it's green.
2. Push to `main` (directly, or via merging a PR).
3. GitHub Actions → `deploy` workflow runs → test gate goes green.
4. You get a notification "production deployment pending review".
5. Open the run → click **Approve and deploy**.
6. Workflow SSHes in, `deploy.sh` runs, smoke passes — site is live.
7. Total time from push to live: ~5–8 minutes (most of it the test gate).

Promotion to **full auto** (skip the approval): in the `production`
environment settings, remove yourself from "Required reviewers". Do this
once you've watched the gate catch a bad change — usually after a few
weeks of production use.

---

## Rotating the deploy key

If the GitHub repo is ever compromised, or you suspect the key leaked:

```bash
# 1. revoke on the VPS
ssh deploy@<VPS_IP>
nano ~/.ssh/authorized_keys     # delete the github-actions-deploy line

# 2. generate a new one + re-run steps 1, 2, 5
```

The `deploy` user is restricted to the docker group + sudo NOPASSWD on the
VPS. If you want tighter blast radius, create a new `ci-deploy` user with
sudo access *only* to the specific deploy commands (search for "sudo
restricted commands" — out of scope here, the simpler form is fine for
a solo project).
