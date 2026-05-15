# CPMAI Prep

Exam-prep platform for the **CPMAI** (Cognitive Project Management for AI)
certification — mock exams with realistic exam-UI affordances (highlight,
strikethrough, mark-for-review), a RAG-grounded AI assistant with an
optional agentic-tool-calling flow, lead capture, admin authoring,
payments (Razorpay + PayPal), and Google sign-in.

> 🎥 **Demo video** — [Watch the walkthrough on LinkedIn](https://www.linkedin.com/posts/mehaboobali-soppadla_ai-generativeai-llm-ugcPost-7460913778612858881-LNXs?utm_source=social_share_send&utm_medium=member_desktop_web&rcm=ACoAACfIQaoBO8SPWaeY17KHBjwdPXiVvplwkUg)
> (business case → live product → architecture → trustworthy-AI mapping).
>
> **Demo preparation** — see [docs/demo-prep.md](docs/demo-prep.md) for the
> demo script, slide outlines, user/admin journeys, and Trustworthy-AI
> mapping.

## Stack

- **Frontend** — Next.js 14 + React + Tailwind + TypeScript
- **Backend** — FastAPI + SQLAlchemy + Alembic
- **Database** — PostgreSQL with `pgvector` for RAG retrieval
- **Cache / rate limits / pubsub** — Redis
- **Payments** — Razorpay (INR rail) + PayPal (non-INR rail), runtime-configurable
- **Auth** — Password (argon2) + Google Sign-In (modular, drop-in module)
- **LLM** — Pluggable provider registry (OpenAI / Anthropic / Azure / Ollama / stub),
  admin-configurable at runtime — no redeploy to swap providers or rotate keys
- **Assistant** — Two orchestration flows, switchable at runtime:
  - **Legacy**: keyword classifier + per-intent handler (5 handlers, RAG-grounded)
  - **Agentic**: LLM router → 7 tool calls (3 RAG, 4 deterministic) → synthesis
- **Observability** — Structured JSONL logs at `backend/logs/app.jsonl`,
  per-turn audit rows, drift detector with operator dashboard
- **Hosting** — Hostinger VPS + Caddy reverse proxy + Docker Compose
  ([why VPS over hyperscaler](docs/design-decisions.md#hostinger-vps-over-aws--azure--gcp))

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

### Production deploy

See [docs/deployment.md](docs/deployment.md) for the full VPS lifecycle.
TL;DR — push to `main`, GitHub Actions runs tests + SSHes to the VPS and
runs `scripts/vps/deploy.sh` (git pull → image rebuild → migrate → seed →
smoke).

## Day-to-day commands

```bash
# health
docker compose ps                    # what's running
tail -f backend/logs/app.jsonl       # journey + audit + http log

# upgrade after pulling code
./scripts/upgrade.sh                 # alembic + seed + smoke + data-preservation

# integration smoke (15 checks across login → CRUD → linkage → public)
python scripts/smoke_admin_crud.py

# pre-push gate (runs locally before git push)
./scripts/preflight.sh               # vitest + backend pytest

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
      admin/            admin-only RBAC-gated endpoints
      assistant.py      /chat + /flag + /resolve + /anon-event
    core/               config · db · auth · audit · logging · settings_store · limiter
    models/             SQLAlchemy models (every table on disk)
    schemas/            Pydantic request/response models
    services/
      assistant/        chat orchestration
        agentic/        agentic flow — tools/ registry + orchestrator
        handlers/       legacy flow — 5 intent handlers
        providers/      LLM providers (OpenAI / Anthropic / stub) + tool-calling
        rag/            retrieve + ingest + sources
        embeddings/     embedding providers (OpenAI text-embedding-3-small)
        drift.py        post-response drift detector (4 rules)
        flow.py         legacy / agentic resolver with cohort hashing
        intent_classifier.py   keyword-based router (admin-tunable)
        orchestrator.py top-level handle() — dispatches to legacy or agentic
      auth/google_auth/ Modular Google Sign-In: verifier · provisioner · service
      geoip/            MaxMind GeoIP lookup for anonymous-visitor tracking
      pricing_service.py  multi-currency quote engine
      lead_scoring.py   rule-based lead score (HOT / WARM / COLD)
  migrations/           Alembic chain (0001 → 0021)
  seeds/                Idempotent seeder + sample data + default_settings.json
  tests/                pytest (unit + integration) — ~360 tests
frontend/
  src/
    app/                Next.js routes
      admin/            assistant-flow · assistant-drift · settings · leads · ...
      dashboard/        learner home
      exams/[slug]/     mock exam UI
    components/
      assistant/        AssistantWidget · widget mount · use-assistant hook
      exam/             AnnotatableText, QuestionCard (drag-highlight & strike)
      lead/             LeadCaptureForm (WhatsApp + country code)
      layout/           LandingTopBar (auth-aware Google button)
    lib/
      api.ts            Typed API client + errMsg helper
      google-auth/      Reusable React Google Sign-In module (drop-in)
    types/api.ts        Shared TypeScript types matching the backend schemas
  __tests__/            vitest specs
design/                 Interactive Vite mockup — design reference, not the live UI
infra/                  Postgres init + pgvector setup, Redis config, nginx (legacy)
docs/                   Architecture, deployment, design decisions, demo prep
scripts/
  bootstrap.sh          First-time setup
  upgrade.sh            Every-deploy entry point (data-preservation guard)
  preflight.sh          Pre-push test gate (mirrors CI)
  preserve_users_check.py   Deploy-time data safety guard
  smoke_admin_crud.py   15-step integration smoke test
  vps/                  Production VPS scripts: provision · install_app · deploy · backup · restore
.github/workflows/      CI: backend / frontend / security-scan / deploy
```

## Features

| Feature | Where |
|---|---|
| Mock exams (drag-highlight & strike, mark-for-review, full review screen) | `/exams/[slug]` |
| Learner dashboard with subscription badge | `/dashboard` |
| AI assistant — RAG-grounded, legacy + agentic flows | Chat bubble (bottom-right of every page) |
| Lead capture (landing form + chat callback + agentic escalation) | `/`, chat widget |
| Admin: questions, exam sets (free/premium toggle, edit time limit) | `/admin/questions`, `/admin/exam-sets` |
| Admin: contacts (leads + users unified, deletable, anonymous-traffic widget) | `/admin/leads` |
| Admin: users with role change | `/admin/users` |
| Admin: FAQ CRUD with on-save embed | `/admin/faqs` |
| Admin: runtime settings (chat limits, landing copy, upsell text, classifier keywords, prompts) | `/admin/settings` |
| Admin: LLM + payment providers, runtime configurable | `/admin/llm-providers`, `/admin/payment-providers` |
| Admin: assistant flow toggle (legacy / agentic / percent / shadow) + live cohort preview | `/admin/assistant-flow` |
| Admin: assistant drift dashboard with side-by-side flow comparison + tool-usage table | `/admin/assistant-drift` |
| Admin: flagged-turns queue (HITL reply + mark-resolved from either side) | `/admin/chat-history/flagged` |
| Admin: chat history per user | `/admin/chat-history` |
| Admin: RAG sources (upload PDF/DOCX/MD, per-source reindex) | `/admin/rag-sources` |
| Admin: international pricing (FX rates, currency selector, GST) | `/admin/pricing` |
| Public landing — admin-editable copy + WhatsApp lead magnet | `/` |
| Auth — Google Sign-In + password, role-aware redirect | `/login` |

## Documentation

| Doc | Purpose |
|---|---|
| [docs/demo-prep.md](docs/demo-prep.md) | Presenter's reference for the demo (slide outlines, talking points) |
| [docs/architecture-overview.md](docs/architecture-overview.md) | Top-level system map — frontend, backend, data, observability |
| [docs/design-decisions.md](docs/design-decisions.md) | Why we chose each major architectural lever |
| [docs/known-limitations.md](docs/known-limitations.md) | Honest constraints + workarounds |
| [docs/agentic-toggle-architecture.md](docs/agentic-toggle-architecture.md) | Agentic flow deep-dive (Mermaid diagram, cost model, rollout strategy) |
| [docs/deployment.md](docs/deployment.md) | Full lifecycle: hosting options, deploy, rollback, CI |
| [docs/vps-deployment-lessons.md](docs/vps-deployment-lessons.md) | Operational gotchas from running prod on the VPS |
| [docs/google-auth-setup.md](docs/google-auth-setup.md) | Google Cloud Console steps for OAuth setup |
| [backend/app/services/auth/google_auth/README.md](backend/app/services/auth/google_auth/README.md) | Backend Google-auth module (drop-in) |
| [frontend/src/lib/google-auth/README.md](frontend/src/lib/google-auth/README.md) | Frontend Google-auth React module (drop-in) |
| [SECURITY.md](SECURITY.md) | Vulnerability disclosure policy |

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

## Tests

- **Backend pytest** — ~360 tests covering unit logic, integration with the
  HTTP layer, and end-to-end flows. Uses in-memory SQLite per test +
  `fakeredis` for isolation. Run via `./scripts/preflight.sh` or
  `docker compose run --rm --no-deps --user 0:0 backend pytest`.
- **Frontend vitest** — 25 React component tests via `npm test` in
  `frontend/`. Covers admin page chrome, assistant widget mount contract,
  country-flag helper, and API credential plumbing.
- **CI** — Both suites run on every push via GitHub Actions before any
  deploy step.

## License

Proprietary. All rights reserved. © CPMAI Prep.
