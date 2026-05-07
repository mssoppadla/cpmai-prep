"use client";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { auth, ApiError, errMsg } from "@/lib/api";
import { GoogleSignInButton } from "@/lib/google-auth";
import type { UserRole } from "@/types/api";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";

/** Where to land after a successful sign-in, based on role. */
function destinationFor(role: UserRole, override: string | null): string {
  if (override) return override;
  return role === "admin" || role === "super_admin" ? "/admin" : "/dashboard";
}

// Next.js requires useSearchParams() to be inside a <Suspense> boundary so the
// rest of the page can prerender. Hence the LoginForm/LoginPage split.
export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginFallback() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
        <div className="h-5 w-24 bg-slate-200 rounded animate-pulse mb-3" />
        <div className="h-4 w-40 bg-slate-100 rounded animate-pulse" />
      </div>
    </main>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const explicitNext = params.get("next");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const tokens = await auth.login({ email, password });
      router.push(destinationFor(tokens.user.role, explicitNext));
    } catch (e) {
      console.error("[login] password sign-in failed", e);
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleGoogleCredential(credential: string) {
    setBusy(true);
    setErr(null);
    try {
      const tokens = await auth.googleLogin(credential);
      router.push(destinationFor(tokens.user.role, explicitNext));
    } catch (e) {
      console.error("[login] google sign-in failed", e);
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900 mb-1">Sign in</h1>
        <p className="text-sm text-slate-600 mb-5">
          Use your CPMAI Prep account.
        </p>
        {GOOGLE_CLIENT_ID && (
          <>
            <div className="flex justify-center mb-4">
              <GoogleSignInButton
                clientId={GOOGLE_CLIENT_ID}
                onCredential={handleGoogleCredential}
                onError={(e) => setErr(e.message)}
              />
            </div>
            <div className="relative my-4">
              <div className="absolute inset-0 flex items-center" aria-hidden="true">
                <div className="w-full border-t border-slate-200" />
              </div>
              <div className="relative flex justify-center">
                <span className="bg-white px-2 text-xs uppercase tracking-wider text-slate-400">or</span>
              </div>
            </div>
          </>
        )}
        <form onSubmit={submit} className="space-y-3" noValidate>
          <input
            required
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full px-4 py-3 text-base border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
            aria-label="Email"
          />
          <input
            required
            type="password"
            autoComplete="current-password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-4 py-3 text-base border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
            aria-label="Password"
          />
          {err && (
            <div role="alert" className="text-sm text-rose-700 bg-rose-50 border border-rose-200 p-2 rounded">
              {err}
            </div>
          )}
          <button
            type="submit"
            disabled={busy}
            className="w-full min-h-[48px] bg-indigo-600 text-white px-6 py-3 text-base font-semibold rounded-lg hover:bg-indigo-700 disabled:opacity-60"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <div className="mt-4 text-xs text-slate-500 text-center">
          <Link href="/" className="hover:text-indigo-600">← Back to landing</Link>
        </div>
      </div>
    </main>
  );
}
