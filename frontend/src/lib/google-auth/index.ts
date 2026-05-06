/**
 * Google Sign-In — reusable React/TypeScript module.
 *
 * Public API:
 *   - <GoogleSignInButton clientId="..." onCredential={...} />  — UI
 *   - useGoogleAuth({ clientId, onSuccess })                    — hook
 *   - postGoogleCredential(credential, endpoint?)              — bare API call
 *   - loadGoogleIdentityServices()                             — manual loader
 *
 * Drop the entire `google-auth/` directory into any React/Next project's
 * src/lib/ folder. No external dependencies beyond React and the Google
 * Identity Services script (loaded on demand from accounts.google.com).
 *
 * See README.md in this directory.
 */
export { GoogleSignInButton } from "./GoogleSignInButton";
export type { GoogleSignInButtonProps } from "./GoogleSignInButton";

export { useGoogleAuth } from "./useGoogleAuth";
export type { UseGoogleAuthOptions } from "./useGoogleAuth";

export { postGoogleCredential } from "./client";
export type { GoogleAuthRequest, GoogleAuthError } from "./client";

export { loadGoogleIdentityServices, isGoogleLoaded } from "./gis-loader";

export type {
  GoogleCredentialResponse, GsiButtonConfig, GoogleIdConfig,
} from "./types";
