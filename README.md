# CPMAI Prep

Exam-prep platform for the **CPMAI** (Cognitive Project Management for AI)
certification — mock exams with detailed reasoning, an AI tutor, lead capture,
admin authoring, payments, and Google sign-in.

## Stack

- **Frontend** — Next.js 14 + React + Tailwind + TypeScript
- **Backend** — FastAPI + SQLAlchemy + Alembic
- **Database** — PostgreSQL  ·  **Cache / Rate-limits** — Redis
- **Payments** — Razorpay (orders + signature-verified webhooks, runtime config)
- **Auth** — Password (argon2) + Google Sign-In (modular, drop-in module)
- **LLM** — Pluggable provider registry (OpenAI / Anthropic / Azure / Ollama / stub),
  admin-configurable at runtime — no redeploy to swap providers
- **Logging** — Structlog mirrored to `backend/logs/app.jsonl` so the user
  journey (auth → exam → submit) is greppable in real time

## Quickstart (local)

Requires Docker Desktop + Python 3.10+ + Node 20+. The bootstrap script
generates secrets, starts the stack, runs migrations, seeds defaults, and
verifies with a smoke test.

```bash
git clone https://github.com/mssoppadla/cpmai-prep
cd cpmai-prep
./scripts/bootstrap.sh

# in another terminal — frontend dev server with HMR
cd frontend && npm install && npm run dev   # http://localhost:3000

# (optional) interactive design mockup
cd design && npm install && npm run dev      # http://localhost:5173
```

The script prints the auto-generated admin password — find it in
`backend/.env` (`BOOTSTRAP_ADMIN_PASSWORD`). Sign in at
**http://localhost:3000/login** with that admin email / password.

## Day-to-day commands

```bash
# health
docker compose ps                    # what's running
tail -f backend/logs/app.jsonl       # journey + audit + http log

# upgrade after pulling code
./scripts/upgrade.sh                 # alembic + seed + smoke + data-preservation

# integration smoke (15 checks across login → CRUD → linkage → public)
python scripts/smoke_admin_crud.py

# add a schema migration
docker compose exec backend bash -c 'cd /app && alembic revision -m "..." --autogenerate'

# DB shell
docker compose exec postgres psql -U cpmai -d cpmai_prep

# promote a Google user to admin
docker compose exec postgres psql -U cpmai -d cpmai_prep \
  -c "UPDATE users SET role='admin' WHERE email='colleague@cpmaiexamprep.com';"
```

## Repo layout

```
backend/                FastAPI service
  app/
    api/v1/endpoints/   public routes + admin/* sub-router
    core/               config · db · auth · audit · logging · settings_store
    models/             SQLAlchemy models (every table on disk)
    services/
      auth/google_auth/ Modular Google Sign-In: verifier · provisioner · service
      ...               exam · razorpay · tracking · settings
  migrations/           Alembic chain (0001 → 0005)
  seeds/                Idempotent seeder + sample data + topics
frontend/
  src/
    app/                Next.js routes (landing · login · admin/* · dashboard · exams/*)
    components/
      exam/             AnnotatableText, QuestionCard (drag-highlight & strike)
      lead/             LeadCaptureForm (WhatsApp + country code)
      layout/           LandingTopBar (auth-aware Google button)
    lib/
      api.ts            Typed API client + errMsg helper
      google-auth/      Reusable React Google Sign-In module (drop-in)
design/                 Interactive Vite mockup — design reference, not the live UI
infra/                  Postgres init, Redis config, nginx
docs/                   Deployment, Google OAuth setup, full lifecycle
scripts/
  bootstrap.sh          First-time setup
  upgrade.sh            Every-deploy entry point (with data-preservation guard)
  preserve_users_check.py   Deploy-time data safety guard
  smoke_admin_crud.py   15-step integration smoke test
.github/workflows/      CI: backend / frontend / security-scan
```

## Features

| Feature | Where |
|---|---|
| Mock exams (drag-highlight & strike, mark-for-review, full review screen) | `/exams/[slug]` |
| Learner dashboard with subscription badge | `/dashboard` |
| Admin: questions, exam sets (free/premium toggle, edit time limit) | `/admin/questions`, `/admin/exam-sets` |
| Admin: contacts (leads + users unified, deletable) | `/admin/leads` |
| Admin: users with role change | `/admin/users` |
| Admin: FAQ CRUD | `/admin/faqs` |
| Admin: runtime settings (chat limits, landing copy, upsell text) | `/admin/settings` |
| Admin: LLM + payment providers, runtime configurable | `/admin/llm-providers`, `/admin/payment-providers` |
| Public landing — admin-editable copy + WhatsApp lead magnet | `/` |
| Auth — Google Sign-In + password, role-aware redirect | `/login` |

## Documentation

- [docs/deployment.md](docs/deployment.md) — full lifecycle, hosting options, rollback, CI
- [docs/google-auth-setup.md](docs/google-auth-setup.md) — Google Cloud Console steps
- [backend/app/services/auth/google_auth/README.md](backend/app/services/auth/google_auth/README.md) — backend Google auth module (drop-in)
- [frontend/src/lib/google-auth/README.md](frontend/src/lib/google-auth/README.md) — frontend Google Sign-In React module (drop-in)
- [SECURITY.md](SECURITY.md) — vulnerability disclosure policy

## Data-preservation guarantee

Three independent layers ensure no deploy ever loses user data:

1. **Additive-only Alembic migrations** — `IF NOT EXISTS` guards, no `DROP`,
   forward-only `downgrade()` raises NotImplementedError.
2. **Idempotent seeder** — settings/topics use upsert-skip; super-admin only
   created if none exists; sample content only inserted into empty tables.
3. **Snapshot guard** — `scripts/preserve_users_check.py` snapshots row counts
   for `users` / `exam_sessions` / `payments` / `subscriptions` / `leads` /
   `audit_logs` / `journey_events` / `exam_attempt_answers` before every
   deploy and refuses to declare success if any count decreased.

Run via `./scripts/upgrade.sh` on every deploy.

## License

Proprietary. All rights reserved. © CPMAI Prep.
