---
name: cpmai-prep-builder
description: Working agreement for building/maintaining a cpmai-prep-class project with Claude. Load alongside CONTEXT.md at the start of every session; follow it for every feature, fix, and deploy.
---

# SKILL — how Claude works on this project

## The loop (every unit of work)

1. **Restate the goal** in one sentence and list the files you expect to
   touch. If a product decision is missing, ask ONE batched question —
   never trickle questions.
2. **Implement** following CONTEXT.md conventions. Small, complete
   changes; schema + types + tests move together.
3. **Test**: run the focused pytest files you touched, then the adjacent
   suites; `npx tsc --noEmit` and the touched vitest files. Fix
   everything, including failures you "inherited" — zero-failure policy.
4. **Verify live**: bring up the dev stack, exercise the feature in the
   browser like a user would, capture proof (response payloads, screen
   reads). Tests prove logic; the browser proves the feature.
5. **Commit** with a conventional message explaining WHY (the diff shows
   what). One logical change per commit.
6. **Push** (pre-push hook runs the full preflight — treat it as CI).
   NEVER edit files while a background push runs: the hook tests the
   working tree.
7. **PR** with problem → fix → verification sections. Base on `main`;
   after a stacked parent merges, rebase children onto main.

## Credential rules (also a guardrails lesson for students)

- Secrets exist ONLY in local `.env` (gitignored) and GitHub Actions
  secrets. The repo carries `.env.example` with placeholders.
- When a flow needs a secret (e.g. admin login for browser verification),
  READ it from the environment and pipe it — never print it, never paste
  it into chat, never hardcode it:
  `PW=$(grep '^BOOTSTRAP_ADMIN_PASSWORD' .env | cut -d= -f2-)` → use `$PW`.
- GitHub: the human runs `gh auth login` once; you use `gh` CLI for
  pushes/PRs and never handle tokens directly.
- If a secret ever lands in a file or output, stop, rotate it, and say so.

## Local dev verification workflow

- Backend tests need no services (SQLite + fakeredis). Full stack for
  browser verification: `docker compose up -d postgres redis`, run the
  backend natively (uvicorn) with `DATABASE_URL` pointed at the mapped
  local port, `npm run dev` for the frontend.
- Fresh DB = `create_all` + `alembic stamp head` + seeder (+ pgvector
  extension + default tenant row) — the migration chain does not run
  from empty by design.
- Admin login for UI checks: POST the bootstrap credentials from `.env`
  to the login API, then set the returned tokens into the browser's
  localStorage. Never type passwords into pages during automation.
- If port 8000 is busy, find out what owns it before killing anything.

## Migration discipline (deploy-gate protecting rules)

- Before touching migrations, alembic env, or deploy workflows: read the
  repo's deployment-lessons doc and reproduce the CI gate locally
  (bootstrapped scratch DB: `create_all` + `stamp head` + `alembic
  check` + `upgrade head`).
- Data migrations: self-contained (no app imports), idempotent
  (WHERE-guarded), zero rows on empty DB, forward-only when reversal
  would be lossy — and say so in the docstring.
- Never edit an already-deployed migration; compensate in a new one or
  at read time.
- Remember `sa.JSON` binds Python `None` as JSON `'null'` text, not SQL
  NULL — target SQL NULL explicitly (`sa.null()`).

## Definition of done (per feature)

- [ ] Tests added in the standard trees and all suites green
- [ ] `tsc --noEmit` clean; vitest green
- [ ] Verified live in the browser with evidence
- [ ] Audit logging on new admin mutations
- [ ] types/api.ts mirrors any schema change
- [ ] No secrets in diff; no state encoded by color alone
- [ ] PR describes problem, fix, and verification

## Communication

- Lead with outcomes; report failures verbatim — never soften a red test.
- When you find an adjacent bug, fix it if it blocks you, otherwise flag
  it for a separate change. Never silently expand scope.
- Never claim "deployed/working" without having verified it.
