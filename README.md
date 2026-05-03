# CPMAI Prep

Paid exam-prep platform for the CPMAI (Cognitive Project Management for AI) certification.

## Stack
- **Frontend**: Next.js 14 + React + Tailwind + TypeScript
- **Backend**: FastAPI + SQLAlchemy + Alembic
- **Database**: PostgreSQL · **Cache/Limits**: Redis
- **Payments**: Razorpay (orders + signature-verified webhooks)
- **AI**: Pluggable LLM provider registry — admin-configurable, no redeploy

## Quickstart

```bash
# 1. Generate secrets and copy env files
cp backend/.env.example  backend/.env
cp frontend/.env.example frontend/.env.local

python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print('ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
# paste the printed values into backend/.env

# 2. Boot the stack
docker compose up --build
```

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- Mockup:   `cd design && npm install && npm run dev` → http://localhost:5173

## Layout
- `backend/`   FastAPI service (RBAC, runtime settings, LLM registry, webhooks)
- `frontend/`  Next.js app (learner + admin)
- `design/`    Interactive UI mockup (Vite + React + Tailwind)
- `infra/`     nginx, postgres, redis, logging stack
- `docs/`      architecture, security, runbooks

See `docs/` and the engineering spec for full implementation details.
