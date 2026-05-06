"use client";
/**
 * useGoogleAuth — convenience hook that wires the GIS callback to your
 * backend's /auth/google endpoint and returns the parsed response.
 *
 * For most callers, this is the only API you need:
 *
 *   const { signIn, busy, error } = useGoogleAuth({
 *     clientId: process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "",
 *     onSuccess: (tokens) => { ... },
 *   });
 *
 *   <GoogleSignInButton clientId={...} onCredential={signIn} />
 *
 * Or use them together via `<GoogleAuthLogin />` if you prefer.
 */
import { useCallback, useState } from "react";
import { postGoogleCredential, type GoogleAuthError } from "./client";

export interface UseGoogleAuthOptions<T = unknown> {
  /** Called with the parsed backend response on success. */
  onSuccess: (response: T) => void | Promise<void>;
  /** Called when the backend rejects the credential or the request fails. */
  onError?: (e: GoogleAuthError) => void;
  /** Override the backend endpoint. Defaults to `/auth/google`. */
  endpoint?: string;
}

export function useGoogleAuth<T = unknown>(opts: UseGoogleAuthOptions<T>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<GoogleAuthError | null>(null);

  const signIn = useCallback(async (credential: string) => {
    setBusy(true);
    setError(null);
    try {
      const response = await postGoogleCredential<T>(credential, opts.endpoint);
      await opts.onSuccess(response);
    } catch (e) {
      const err = (e as GoogleAuthError);
      setError(err);
      opts.onError?.(err);
    } finally {
      setBusy(false);
    }
  }, [opts]);

  return { signIn, busy, error };
}
