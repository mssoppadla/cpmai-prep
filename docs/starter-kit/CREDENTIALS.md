# CREDENTIALS — every secret, where it comes from, and the handling rules

**The three rules (teach these before anything else):**
1. Secrets live in local `.env` files (gitignored) and GitHub Actions
   secrets — nowhere else. The repo ships `.env.example` with
   placeholders only.
2. Claude/tools READ secrets from the environment when a flow needs them
   (piped into commands) and never print, paste, commit, or restate
   them. If one leaks into output or a file: stop, rotate, disclose.
3. Every student uses their OWN sandbox/test accounts. Never share keys,
   never use production keys while learning.

## GitHub access (recommended: keep this model)

- One-time, human-run: `gh auth login` (browser device flow). The token
  is stored by GitHub CLI in the OS credential manager.
- From then on Claude uses `gh` / `git push` without ever seeing a
  token. CI deploys use a **dedicated deploy SSH keypair** whose private
  key lives only in a GitHub Actions secret; the public key goes in the
  VPS deploy user's `authorized_keys`.

## Backend `.env` (placeholders — copy to `.env` and fill)

| Key | Purpose | Where to get it |
|---|---|---|
| `SECRET_KEY` | JWT signing | generate: `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `ENCRYPTION_KEY` | Fernet key for provider API keys at rest | `python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"` |
| `DATABASE_URL` | Postgres DSN | your compose/local values |
| `REDIS_URL` | Redis DSN | your compose/local values |
| `BOOTSTRAP_ADMIN_EMAIL/_PASSWORD` | first super-admin, seeded | choose; **rotate via admin UI after first login** |
| `SMOKE_ADMIN_EMAIL/_PASSWORD` | deploy smoke-test account | generated at install; never used by humans |
| `GOOGLE_CLIENT_ID/_SECRET` | Google sign-in | Google Cloud Console → OAuth client (add localhost + prod origins) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | LLM + embeddings (or enter via admin provider UI, encrypted) | platform.openai.com / console.anthropic.com |
| `RAZORPAY_KEY_ID/_SECRET` | payments (TEST mode while learning) | dashboard.razorpay.com → test keys |
| `PAYPAL_CLIENT_ID/_SECRET` | payments sandbox | developer.paypal.com sandbox app |
| `SMTP_HOST/_PORT/_USER/_PASSWORD` | email sending | your provider (app-password, not account password) |

Frontend `.env`: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID`
(public by design — nothing sensitive may ever be `NEXT_PUBLIC_`).

## GitHub Actions secrets (repo → Settings → Secrets)

`VPS_HOST`, `VPS_SSH_KEY` (deploy private key), plus test-job values the
CI generates per-run (e.g. ephemeral `ENCRYPTION_KEY`) rather than
storing real ones.

## Patterns Claude must use (examples)

```bash
# Login for browser verification WITHOUT exposing the password:
PW=$(grep '^BOOTSTRAP_ADMIN_PASSWORD' backend/.env | cut -d= -f2-)
TOK=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PW\"}" | jq -r .access)
# $TOK may be used in headers; the password variable is never echoed.
```

- Masking when displaying config: `sed 's/:[^:@]*@/:***@/'` on DSNs.
- Provider keys entered through the admin UI are encrypted with
  `ENCRYPTION_KEY` before storage — the DB never holds plaintext keys.

## Rotation & hygiene

- Rotate the bootstrap admin password via the UI right after install;
  deploy smoke uses its own account so rotation never breaks deploys.
- `.env` file mode: readable by the app user; treat the file like a
  password manager export. Never screenshot it.
- Quarterly: rotate LLM + payment keys; GitHub deploy key on team
  changes.
