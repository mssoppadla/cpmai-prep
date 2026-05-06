# Google OAuth Auth Module

Reusable Google Sign-In verification + user provisioning for any Python
backend (FastAPI / Flask / Django / standalone).

## What this module does

1. **Verifies** a Google-issued OIDC `id_token` (signature, issuer,
   audience, expiry, email-verified).
2. **Finds-or-creates** a user row in your database.
3. Hands the user back to your code so *you* issue your own session tokens.

## What this module deliberately does NOT do

- **Issue session tokens.** Every project does this differently
  (JWT in body, JWT in cookie, NextAuth, etc.). Call your existing
  token-issuing code with the user that `authenticate()` returns.
- **Render UI.** Use the matching frontend module
  (`frontend/src/lib/google-auth/`) or wire the Google Identity Services
  JS library yourself.
- **Manage refresh.** Once authenticated, your session manages
  itself — Google's refresh tokens are not required for this flow.

## Architecture

    ┌──────────────────────────┐
    │      verifier.py         │  pure function, no DB, no framework
    │  verify_google_id_token  │  → returns claims dict
    └────────────┬─────────────┘
                 │
    ┌────────────▼─────────────┐
    │     provisioner.py       │  Protocol + DefaultSqlAlchemyProvisioner
    │  find_or_create(claims)  │  → returns your User object
    └────────────┬─────────────┘
                 │
    ┌────────────▼─────────────┐
    │       service.py         │  ties verifier + provisioner
    │   GoogleAuthService      │  → call .authenticate(credential)
    └──────────────────────────┘

## Usage in this project

```python
from app.services.auth.google_auth import (
    GoogleAuthConfig, GoogleAuthService, DefaultSqlAlchemyProvisioner,
    InvalidTokenError, NotConfiguredError, AccountInactiveError,
)
from app.models.user import User, UserRole

config = GoogleAuthConfig.from_env()  # reads GOOGLE_OAUTH_CLIENT_ID
provisioner = DefaultSqlAlchemyProvisioner(db, User, UserRole)
service = GoogleAuthService(config, provisioner)

try:
    user = service.authenticate(credential)
except NotConfiguredError:
    # Server-side: feature is off
    raise HTTPException(503, "Google sign-in is not configured")
except InvalidTokenError:
    raise HTTPException(401, "Invalid Google credential")
except AccountInactiveError:
    raise HTTPException(403, "Account disabled")

# Now hand `user` to your existing token-issuing code
access_token, refresh_token = AuthService(db)._issue(user)
```

## Drop-in for another project

1. **Copy this directory** into your project's services tree, e.g.
   `myapp/services/google_auth/`.
2. **Add the dependency**: `google-auth>=2.34.0` to your requirements.
3. **Set the env var**: `GOOGLE_OAUTH_CLIENT_ID=<your-client-id>`. (Optional:
   `GOOGLE_OAUTH_ALLOWED_CLIENT_IDS=<csv>` for additional accepted audiences.)
4. **Implement a provisioner** if your User model differs from this repo's.
   The default lookups by `google_id` then `email`; replace with your own
   class implementing the `UserProvisioner` Protocol:

   ```python
   class MyProvisioner:
       def find_or_create(self, claims: GoogleClaims) -> MyUser:
           # your logic here
           ...
   ```

5. **Wire one route** that takes a `credential` string and calls
   `service.authenticate(credential)`. See `app/api/v1/endpoints/auth.py`
   in this repo for a complete FastAPI example.

## Setting up the Google OAuth client

See [docs/google-auth-setup.md](../../../../docs/google-auth-setup.md) at
the repo root for step-by-step Google Cloud Console instructions.

## Security notes

- The verifier checks **signature, issuer, audience, expiry, and
  email-verified** by default. The audience check rejects tokens issued
  for any other Google client — important if your backend serves
  multiple frontends with different client IDs.
- The default provisioner **never elevates roles** on Google sign-in.
  Existing admins keep admin (matched by email); new Google sign-ups
  always get `default_role` (= `user`).
- Disabled accounts (`is_active = False`) are rejected before token
  issuance — disabling a user via your admin UI immediately blocks
  Google logins.
