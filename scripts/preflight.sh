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

  # Skip `next build` on Windows. @vercel/og (used by /twitter-image)
  # calls fileURLToPath() with a Windows-style path during prerender →
  # TypeError: Invalid URL. Linux Docker build (prod) and Linux CI are
  # unaffected. See vps-deployment-lessons.md row #22.
  if [[ "$OSTYPE" == msys* ]] || [[ "$OSTYPE" == cygwin* ]] \
     || uname -s 2>/dev/null | grep -qi mingw; then
    warn "windows detected — skipping 'next build' (known @vercel/og bug)"
    warn "                   CI runs on Linux and will catch real build issues."
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
  fi
else
  warn "SKIP_FRONTEND=1 — skipping frontend checks"
fi

# ------------------------------------------------------------------------------
# Backend — pytest. Uses Docker if running so we don't depend on the user
# having a Python venv with dev deps. If the stack isn't up, we skip with a
# warning — CI will catch backend regressions.
# ------------------------------------------------------------------------------
if [ -z "${SKIP_BACKEND:-}" ]; then
  if docker compose ps backend --status running --quiet 2>/dev/null | grep -q .; then
    say "backend: pytest (via docker)"
    docker compose exec -T backend pytest -q \
      || die "backend tests failed"
    ok "backend tests green"
  elif command -v pytest >/dev/null 2>&1 && [ -d backend ]; then
    say "backend: pytest (host venv)"
    ( cd backend && pytest -q ) || die "backend tests failed"
    ok "backend tests green"
  else
    warn "skipping backend pytest — neither 'docker compose' has backend"
    warn "running, nor pytest is on PATH. CI will still catch issues."
  fi
else
  warn "SKIP_BACKEND=1 — skipping backend checks"
fi

ELAPSED=$(( $(date +%s) - START ))
echo
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
echo "${G}✓ preflight green${X} in ${ELAPSED}s — safe to push"
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
