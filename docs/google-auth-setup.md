# Setting up Google Sign-In

## 1. Create a Google OAuth Web Client

1. Open <https://console.cloud.google.com/apis/credentials>.
2. Pick (or create) a project for this app.
3. **Configure OAuth consent screen** if you haven't already:
   - User Type: **External**
   - App name, support email, dev contact email — fill in
   - Save through to dashboard
4. Click **Create Credentials → OAuth client ID**.
5. **Application type**: **Web application**.
6. **Name**: anything, e.g. `cpmai-prep-dev`.
7. **Authorized JavaScript origins** — add the URLs your frontend
   actually runs at:
   - `http://localhost:3000` (Next.js dev)
   - your staging / production origins
   - **Do not** add a path; only the origin (scheme + host + port).
8. **Authorized redirect URIs** — leave empty. Google Identity Services
   uses postMessage, not redirects.
9. **Create**. Copy the **Client ID** (looks like
   `123456789-abcdef.apps.googleusercontent.com`).

## 2. Configure the backend

Edit `backend/.env`:

```bash
GOOGLE_OAUTH_CLIENT_ID=123456789-abcdef.apps.googleusercontent.com
# Optional: for mobile/native variants of the same project
GOOGLE_OAUTH_ALLOWED_CLIENT_IDS=
```

Restart the backend so it picks up the env var:

```bash
docker compose up -d --force-recreate backend
```

Verify the endpoint moves from `503` to `401` (rejecting bogus tokens
with the right code now means it's configured):

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/google \
  -H "Content-Type: application/json" \
  -d '{"credential":"bogus"}' | jq .
# Expect: {"error": {"code": "unauthorized", "message": "Invalid Google credential: ..."}}
```

## 3. Configure the frontend

Edit `frontend/.env.local`:

```bash
NEXT_PUBLIC_GOOGLE_CLIENT_ID=123456789-abcdef.apps.googleusercontent.com
```

Restart the dev server (Next.js needs a cold start to pick up new
`NEXT_PUBLIC_*` env vars):

```bash
# stop the running dev server first, then:
npm --prefix frontend run dev
```

Open <http://localhost:3000/login> — you should see Google's official
"Continue with Google" button above the email/password form. Sign in;
the page redirects to `/admin` (or whatever `?next=` URL was passed).

## 4. Verify the user journey

After your first Google sign-in:

```bash
# DB row was created with google_id linked:
PGPASSWORD=cpmai_dev psql -h localhost -p 5433 -U cpmai -d cpmai_prep \
  -c "SELECT id, email, name, role, google_id IS NOT NULL AS has_google FROM users ORDER BY id;"

# Journey events recorded:
grep '"event_name"' backend/logs/app.jsonl | tail -10
```

You should see entries like:
```json
{"event":"journey","event_name":"auth.signup.google","user_id":2,"email":"you@example.com","level":"info"}
{"event":"journey","event_name":"auth.login.google","user_id":2,"first_time":true,"level":"info"}
```

## How role assignment works

| Sign-in scenario | What happens |
|---|---|
| First time, email is new | New row, `role='user'`, `google_id` set, no password |
| First time, email matches an existing password account | Existing row gets `google_id` linked. **Role is preserved** — admins keep admin |
| Repeat sign-in | Matched on `google_id`, no DB write except `last_login_at` |
| Account is `is_active=false` | 403, no token issued |

Google sign-in **never elevates** a regular user to admin. Use the
admin user-management UI to grant roles.

## Disabling Google sign-in

Leave `GOOGLE_OAUTH_CLIENT_ID` empty (in either backend or frontend).
The frontend button hides; the backend returns `503 google_not_configured`
for any `/auth/google` call. Password login keeps working unchanged.

## Drop-in to another project

The auth code is packaged so you can lift it into a different project:

- **Backend**: `backend/app/services/auth/google_auth/` — see its
  README for instructions.
- **Frontend**: `frontend/src/lib/google-auth/` — see its README.

Both directories are self-contained. Each has its own README explaining
the public API and how to wire it up.
