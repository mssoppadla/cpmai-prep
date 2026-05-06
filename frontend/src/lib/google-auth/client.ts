/**
 * Backend API caller for Google sign-in.
 *
 * Posts the GIS-issued credential to your project's auth endpoint.
 * Reads the API base URL from NEXT_PUBLIC_API_URL with a sensible fallback.
 */

const API_BASE = (typeof process !== "undefined"
  && process.env?.NEXT_PUBLIC_API_URL) || "http://localhost:8000/api/v1";

export interface GoogleAuthRequest {
  credential: string;
}

export interface GoogleAuthError {
  status: number;
  code: string;
  message: string;
}

/**
 * POST /auth/google. Returns the parsed body on 2xx, or throws a
 * `GoogleAuthError` with a stable shape.
 *
 * Generic over the response body so projects can plug in their own
 * AuthTokens type. Default is `unknown` to keep this lib decoupled.
 */
export async function postGoogleCredential<T = unknown>(
  credential: string,
  endpoint: string = "/auth/google",
): Promise<T> {
  const url = endpoint.startsWith("http") ? endpoint : `${API_BASE}${endpoint}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ credential } satisfies GoogleAuthRequest),
  });

  let body: any = null;
  const txt = await res.text();
  if (txt) {
    try { body = JSON.parse(txt); } catch { /* leave as raw text below */ }
  }

  if (!res.ok) {
    const err = body?.error ?? {};
    throw {
      status: res.status,
      code: err.code ?? "google_auth_failed",
      message: err.message ?? `HTTP ${res.status}`,
    } satisfies GoogleAuthError;
  }
  return body as T;
}
