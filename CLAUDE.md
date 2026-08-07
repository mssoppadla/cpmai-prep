# CLAUDE.md — operating rules for this repo

Hard-won rules from real production incidents (2026-08, documented as
rows 38–40 in `docs/vps-deployment-lessons.md`). Follow them; every one
exists because skipping it broke prod.

## Before writing any fix

1. **Confirm the issue first.** Reproduce it (local browser stack, curl,
   logs, `/admin/error-logs`) or have the user validate the diagnosis —
   THEN propose the fix and get a go-ahead. Never ship speculative fixes
   or "just in case" instrumentation. (An unconfirmed theory once shipped
   code that would have crashed the API on boot; the actual bug was a
   stale login session.)
2. State what you found and what the fix will provide before editing files.

## Database & migrations

3. **Never DELETE / TRUNCATE / DROP rows of a guarded table** —
   `users`, `exam_sessions`, `exam_attempt_answers`, `payments`,
   `subscriptions`, `leads`, `audit_logs`, `journey_events` (the live
   list is `GUARDED_TABLES` in `scripts/preserve_users_check.py`).
   deploy.sh aborts and auto-rolls-back the whole deploy when a guarded
   table loses rows — from a migration OR from a user-triggered code
   path running mid-deploy. Mark rows with a status every read path
   filters out (`abandoned`, `deleted`) instead. `preflight.sh` has a
   static gate for this; `ALLOW_GUARDED_DELETE=1` overrides only for a
   reviewed, intentional cleanup.
4. **Rehearse the deploy, not just the tests:** run
   `./scripts/rehearse_deploy.sh` (guard snapshot → `alembic upgrade
   head` → guard verify → downgrade → re-upgrade) against the local
   compose Postgres before pushing anything that touches
   `backend/migrations/`, `docker-compose*`, or `scripts/vps/`.
   pytest passing is NOT evidence a deploy will survive.
5. Migration revision ids ≤32 chars (`alembic_version` column limit).
   The alembic chain is NOT runnable from an empty DB (`0001` is a
   stamp baseline) — fresh DBs use `create_all` + `stamp head`.

## VPS / infra (the drift rules)

6. **The repo is not the live server.** Before applying any config file
   to the VPS, diff it against the live copy first
   (`diff infra/Caddyfile /etc/caddy/Caddyfile`). The live file is the
   truth about ports and hosts. Blindly applying the repo Caddyfile
   502'd all of prod (row 39).
7. Caddy upstreams are `127.0.0.1:3001` (frontend) / `127.0.0.1:8001`
   (backend) — the VPS overrides compose's default ports via
   `.deploy.conf`, and Caddy resolves `localhost` to `::1` while the
   containers publish IPv4 only. HTTP/3 stays disabled (`protocols h1
   h2`): UDP/443 dies on some network paths and the cached Alt-Svc hint
   stalls those users for 30 days.
8. Caddy changes: hot-load via the no-sudo admin API (`caddy adapt
   --config infra/Caddyfile | curl -X POST localhost:2019/load ...`),
   then persist with `sudo cp` + `caddy validate` + `systemctl reload`
   (reload, never restart). A reboot silently reverts an unpersisted
   hot-load.
9. **Verify with status codes, never header greps.** `curl -s -o
   /dev/null -w "%{http_code}" https://cpmaiexamprep.com` — a 502 will
   happily "pass" a `grep alt-svc` check (it did).

## Destructive scripts & backups

10. **Stage → verify → swap.** Never wipe live data before the
    replacement is fully extracted and verified (restore.sh once wiped
    all prod uploads because the wipe ran before a restore command that
    could never succeed — row 40).
11. Never print a success message after `|| warn`. If it can fail, the
    failure must be loud and the summary honest.
12. Sandbox-test destructive script changes before pushing: build the
    corrupt/empty/good inputs and prove the failure modes are no-ops.
13. Suspiciously small backup archives (~100 bytes = empty tar.gz) mean
    the source was already empty — restoring one certifies data loss.

## Push & test hygiene

14. The pre-push hook runs `scripts/preflight.sh` against the WORKING
    TREE — never edit files while a push is running.
15. Zero tolerance for "pre-existing" test failures: if the suite is
    red, fix it — a baseline failure means an earlier PR shipped it.
16. Stacked-PR trap: PRs merge into their configured base at merge
    time. After a parent PR merges, rebase/branch follow-ups off main
    and verify commits actually reached `origin/main` before trusting
    "deployed". (Two Caddyfile fixes were once stranded on a merged
    PR's branch while main stayed broken.)
17. Background pushes: judge success by the task's completion record
    and `git ls-remote`, not by piped exit codes (`| tail` masks
    failures).

## Local environment quirks

18. Backend tests: `backend/.venv312` (host Python 3.14 has no wheels
    for the pins). Full local browser stack: compose postgres on host
    port 5433 + venv uvicorn wrapper + token-injection login — see the
    session-memory `project_local_test_run` for the recipe.
19. `next build` is skipped on Windows (@vercel/og prerender bug);
    preflight builds the Linux Docker image instead.
