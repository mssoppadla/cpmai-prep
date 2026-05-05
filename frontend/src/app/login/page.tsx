"use client";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { auth, ApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/admin";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await auth.login({ email, password });
      router.push(next);
    } catch (e) {
      setErr((e as ApiError).body?.message ?? "Sign in failed");
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
