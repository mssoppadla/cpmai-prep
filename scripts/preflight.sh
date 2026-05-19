#!/usr/bin/env bash
# ==============================================================================
# preflight.sh — local equivalent of the CI test gate.
# ==============================================================================
# Runs everything the GitHub Actions deploy.yml `test` job runs, in the
# same order. Goal: when this passes locally, CI will pass; when it
# fails, you find out in 30 seconds instead of 3 minutes after pushing.
#
# Used by the pre-push git hook (.githooks/pre-push) so a `git push`
# can't ship known-broken code, but also runnable manually any time:
#
#     ./scripts/preflight.sh           # all checks
#     SKIP_BACKEND=1 ./scripts/preflight.sh   # frontend only (faster)
#     SKIP_FRONTEND=1 ./scripts/preflight.sh  # backend only
#
# Exit code is non-zero on any failure; pre-push hook propagates it.
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
B=$'\033[1m'; G=$'\033[0;32m'; Y=$'\033[0;33m'; C=$'\033[0;36m'; R=$'\033[0;31m'; X=$'\033[0m'
say()  { echo "${C}→${X} $*"; }
ok()   { echo "${G}✓${X} $*"; }
warn() { echo "${Y}!${X} $*" >&2; }
die()  { echo "${R}✗${X} $*" >&2; exit 1; }

# Track which checks ran vs were deferred to CI, so we can print a
# transparent coverage summary at the end.
declare -a RAN=() DEFERRED=()
ran()      { RAN+=("$*"); }
deferred() { DEFERRED+=("$*"); }

START=$(date +%s)

# ------------------------------------------------------------------------------
# Frontend — vitest unit tests + strict next build
# ------------------------------------------------------------------------------
if [ -z "${SKIP_FRONTEND:-}" ]; then
  if [ ! -d frontend/node_modules ]; then
    warn "frontend/node_modules missing — running npm ci first"
    ( cd frontend && npm ci --no-audit --no-fund )
  fi

  say "frontend: vitest"
  ( cd frontend && npm test ) || die "frontend tests failed"
  ok "frontend tests green"
  ran "frontend vitest unit tests"

  # ALWAYS run strict TypeScript typecheck. Vitest uses esbuild and only
  # compiles files actually imported by tests, so type errors elsewhere
  # slip through. ``tsc --noEmit`` is cross-platform (unlike `next build`
  # which has the @vercel/og Windows incompat), fast (~10s), and catches
  # everything CI's `next build` typecheck step does. This closes the
  # gap where a TS error reaches the CI gate uncaught.
  say "frontend: tsc --noEmit (strict typecheck)"
  ( cd frontend && npx tsc --noEmit ) || die "frontend typecheck failed (fix TS errors above)"
  ok "frontend typecheck green"
  ran "frontend tsc --noEmit"

  # Skip `next build` on Windows. @vercel/og (used by /twitter-image)
  # calls fileURLToPath() with a Windows-style path during prerender →
  # TypeError: Invalid URL. Linux Docker build (prod) and Linux CI are
  # unaffected. See vps-deployment-lessons.md row #22.
  if [[ "$OSTYPE" == msys* ]] || [[ "$OSTYPE" == cygwin* ]] \
     || uname -s 2>/dev/null | grep -qi mingw; then
    warn "windows detected — skipping 'next build' (known @vercel/og bug)"
    warn "                   CI runs on Linux and will catch real build issues."
    deferred "frontend next build (Windows-only @vercel/og incompat)"
  else
    say "frontend: next build (catches TS + prerender errors)"
    # Build env vars match what the CI workflow uses — keep these in sync
    # with .github/workflows/deploy.yml's "Frontend build (strict)" step.
    (
      cd frontend
      NEXT_PUBLIC_API_URL="http://localhost:8000/api/v1" \
      NEXT_PUBLIC_GOOGLE_CLIENT_ID="" \
      NEXT_PUBLIC_RAZORPAY_KEY_ID="" \
      NEXTAUTH_URL="http://localhost:3000" \
      NEXTAUTH_SECRET="preflight-not-used-in-prod" \
        npm run build >/dev/null 2>&1
    ) || die "frontend build failed (run 'cd frontend && npm run build' to see the error)"
    ok "frontend build green"
    ran "frontend next build (TS + prerender)"
  fi
else
  warn "SKIP_FRONTEND=1 — skipping frontend checks"
fi

# ------------------------------------------------------------------------------
# Backend — pytest. We must run against THIS checkout's backend code (not
# whatever code happens to be in some other running container). Strategies
# in order of preference:
#
#   1. Running backend container exists AND its /app bind-mount points at
#      THIS repo's backend dir → exec pytest in it (fastest; reuses image).
#   2. Docker compose available → `docker compose run --rm --no-deps backend`
#      from this dir. Compose mounts ./backend correctly, builds once,
#      no port collision with any parent-repo container.
#   3. Host has pytest on PATH → run there.
#   4. Otherwise: fail loudly. Bypass with SKIP_BACKEND=1 for doc-only pushes.
#
# Why the bind-mount check matters: with git worktrees, the parent repo
# may have a backend container running with /app bound to the parent's
# backend dir. Exec'ing pytest there tests stale code, not the worktree's
# pending push — silently passes/fails the wrong commit.
# ------------------------------------------------------------------------------
if [ -z "${SKIP_BACKEND:-}" ]; then
  REPO_BACKEND_DIR="$(pwd)/backend"

  # Look for ANY running backend container (any compose project).
  RUNNING_BACKEND=$(docker ps --filter "name=backend-1" --filter "status=running" \
                     --format "{{.Names}}" 2>/dev/null | head -1)

  # If one is running, check whether its /app bind matches THIS backend.
  CONTAINER_USABLE=""
  if [ -n "$RUNNING_BACKEND" ]; then
    BIND_SRC=$(docker inspect "$RUNNING_BACKEND" \
                --format '{{range .Mounts}}{{if eq .Destination "/app"}}{{.Source}}{{end}}{{end}}' \
                2>/dev/null)
    # Normalise both paths for comparison (Windows mixes / and \, and
    # case differs between Git Bash and Docker Desktop output).
    norm() { echo "$1" | tr '[:upper:]' '[:lower:]' | tr '\\' '/'; }
    if [ "$(norm "$BIND_SRC")" = "$(norm "$REPO_BACKEND_DIR")" ]; then
      CONTAINER_USABLE=1
    else
      warn "running container '$RUNNING_BACKEND' is bound to a DIFFERENT backend dir:"
      warn "    container /app → $BIND_SRC"
      warn "    this checkout → $REPO_BACKEND_DIR"
      warn "    will run pytest in an ephemeral compose container instead."
    fi
  fi

  if [ -n "$CONTAINER_USABLE" ]; then
    # Prod-shaped image doesn't ship pytest. Install dev deps once;
    # subsequent runs are fast because deps already in the container.
    # `sh -c` so Git Bash doesn't munge /app paths. `-u 0` to write as
    # root (the prod image's app user can't update its own site-packages,
    # since /home/app/.local was COPY'd in from the build stage).
    if ! docker exec "$RUNNING_BACKEND" sh -c "command -v pytest >/dev/null 2>&1"; then
      say "backend: installing test deps inside container (one-time)..."
      docker exec -u 0 "$RUNNING_BACKEND" sh -c "pip install --quiet -r /app/requirements-dev.txt" \
        || die "could not install test deps in container"
    fi
    say "backend: pytest (via running container '$RUNNING_BACKEND')"
    docker exec -u 0 "$RUNNING_BACKEND" sh -c "cd /app && pytest -q" || die "backend tests failed"
    ok "backend tests green"
    ran "backend pytest (running container)"

  elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    say "backend: pytest via 'docker compose run --rm --no-deps backend' (mounts this checkout)"
    # --no-deps: tests use sqlite + fakeredis, don't need postgres/redis.
    # --user 0:0: prod image's app user can't write to /home/app/.local
    #             (was COPY'd from build stage as root). Need root to pip-install
    #             dev deps into site-packages.
    # First run builds the image (~30s); subsequent runs reuse it.
    docker compose run --rm --no-deps --user 0:0 backend \
      sh -c "pip install --quiet -r /app/requirements-dev.txt && cd /app && pytest -q" \
      || die "backend tests failed"
    ok "backend tests green"
    ran "backend pytest (ephemeral compose run)"

  elif command -v pytest >/dev/null 2>&1 && [ -d backend ]; then
    say "backend: pytest (host venv)"
    ( cd backend && pytest -q ) || die "backend tests failed"
    ok "backend tests green"
    ran "backend pytest (host venv)"

  else
    die "cannot run backend tests — install Docker (preferred) or pip install -r backend/requirements-dev.txt. Bypass with SKIP_BACKEND=1 if intentional."
  fi
else
  warn "SKIP_BACKEND=1 — skipping backend checks"
fi

ELAPSED=$(( $(date +%s) - START ))
echo
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
echo "${G}✓ preflight green${X} in ${ELAPSED}s"
echo
echo "  ${G}Ran locally${X} (${#RAN[@]}):"
for item in "${RAN[@]}"; do
  echo "    ✓ $item"
done
if [ "${#DEFERRED[@]}" -gt 0 ]; then
  echo
  echo "  ${Y}Deferred to CI${X} (${#DEFERRED[@]}):"
  for item in "${DEFERRED[@]}"; do
    echo "    · $item"
  done
fi
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
