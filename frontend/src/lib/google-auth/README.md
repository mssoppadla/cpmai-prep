# Google Sign-In — reusable React/TypeScript module

Drop-in Google Sign-In for any React or Next.js project. Just the UI +
the network call to your backend's `/auth/google` endpoint. The backend
verifies the credential and issues your session tokens; this module
doesn't touch your auth state.

## Files

| File | Role |
|---|---|
| `index.ts` | Public exports — import from here |
| `GoogleSignInButton.tsx` | React component rendering Google's official button |
| `useGoogleAuth.ts` | Hook that wires the credential to your backend |
| `client.ts` | `fetch()`-based caller for `POST /auth/google` |
| `gis-loader.ts` | Idempotent loader for the GIS script |
| `types.ts` | TypeScript types for `window.google.accounts.id` |

## Quick start

```tsx
import { GoogleSignInButton, useGoogleAuth } from "@/lib/google-auth";

const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";

function LoginPage() {
  const { signIn, busy, error } = useGoogleAuth({
    onSuccess: (tokens) => {
      // store tokens and redirect
      // e.g. localStorage.setItem("token", tokens.access)
    },
  });

  return (
    <>
      <GoogleSignInButton clientId={clientId} onCredential={signIn} />
      {busy && <p>Signing in…</p>}
      {error && <p role="alert">{error.message}</p>}
    </>
  );
}
```

If `clientId` is empty (env var unset), the component renders nothing —
so you can ship the same code in environments where Google sign-in
isn't configured.

## Drop-in for another project

1. **Copy the directory** into your project's `src/lib/` (or wherever
   your aliases point).
2. **Set the env var** that exposes your client ID to client code,
   e.g. `NEXT_PUBLIC_GOOGLE_CLIENT_ID`.
3. **Set the API base URL** (default reads `NEXT_PUBLIC_API_URL`).
4. **Use the hook + button** as shown above. If your backend's Google
   route lives at a different path, pass `endpoint` to either
   `useGoogleAuth` or `postGoogleCredential`.

That's it — no other config, no global providers, no Context. The hook
manages its own busy/error state.

## Server side

The backend endpoint must:
- Accept `{ "credential": "<jwt>" }` POST body
- Verify the JWT against Google's JWKS using your client ID as `aud`
- Look up or create a user
- Return whatever shape your app expects (this module is generic over
  the response type — declare it as the type parameter to
  `useGoogleAuth<MyTokens>` / `postGoogleCredential<MyTokens>`)

This repo's matching backend lives at
[`backend/app/services/auth/google_auth/`](../../../../backend/app/services/auth/google_auth/) — drop that into your Python backend
the same way.

## Setting up the Google OAuth client

Create a Web Application OAuth 2.0 Client at
<https://console.cloud.google.com/apis/credentials>. Add your origin
(e.g. `http://localhost:3000`) under **Authorized JavaScript origins**.
You don't need a redirect URI — GIS uses postMessage. Copy the client
ID and put it in your env. See the repo-level
[docs/google-auth-setup.md](../../../../docs/google-auth-setup.md) for
step-by-step instructions.
