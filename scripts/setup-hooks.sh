#!/usr/bin/env bash
# ==============================================================================
# setup-hooks.sh — one-time activation of the local git hooks.
# ==============================================================================
# Run this ONCE per clone of the repo. Idempotent — safe to re-run.
#
# What it does: points `git config core.hooksPath` at the tracked
# .githooks/ directory, so hooks like pre-push (which runs preflight.sh
# before every `git push`) are active. Without this step the local
# .git/hooks/ folder is empty and the hooks don't fire.
#
#     ./scripts/setup-hooks.sh
#
# Why we don't just write into .git/hooks/: that directory is per-clone
# and not committed, so any setup there has to be re-done every time
# someone clones the repo. core.hooksPath lets us track hooks in git
# while still leaving them opt-in (you can disable per-repo with
# `git config --unset core.hooksPath`).
# ==============================================================================
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

current=$(git config --get core.hooksPath)
echo "✓ git hooks active — core.hooksPath = ${current}"
echo "  Pre-push will now run scripts/preflight.sh before every 'git push'."
echo "  Bypass with: git push --no-verify   (or)   SKIP_PREFLIGHT=1 git push"
