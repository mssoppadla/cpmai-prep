"use client";
/**
 * LandingTopBar — auth-aware header for the landing page.
 *
 * On mount it calls /users/me. If the visitor has a valid session, it
 * shows a "Continue to dashboard" button (admins go to /admin, learners
 * to /dashboard). Otherwise it renders a Google sign-in button + a
 * link to the password login page.
 *
 * Renders nothing client-side until the auth check resolves, so the
 * landing page doesn't flash the wrong state. The SEO content below
 * is server-rendered and unaffected.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/api";
import { GoogleSignInButton } from "@/lib/google-auth";
import type { UserOut } from "@/types/api";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";

function destinationFor(role: UserOut["role"]): string {
  return role === "admin" || role === "super_admin" ? "/admin" : "/dashboard";
}

export function LandingTopBar() {
  const router = useRouter();
  const [me, setMe] = useState<UserOut | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const u = await auth.me();
        if (!cancelled) setMe(u);
      } catch {
        // Try refresh once before giving up
        const ok = await auth.refresh();
        if (cancelled) return;
        if (!ok) { setMe(null); return; }
        try { setMe(await auth.me()); } catch { setMe(null); }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  async function handleGoogle(credential: string) {
    try {
      const tokens = await auth.googleLogin(credential);
      router.push(destinationFor(tokens.user.role));
    } catch {
      // Worst case: fall back to /login so the user sees the error
      router.push("/login");
    }
  }

  return (
    <div className="border-b border-slate-200 bg-white/80 backdrop-blur supports-[backdrop-filter]:bg-white/60">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between gap-3">
        <Link href="/" className="font-bold text-slate-900">
          CPMAI Prep
        </Link>

        {/* Three states: loading | signed-in | signed-out */}
        {me === undefined ? (
          <div className="h-9 w-32 bg-slate-100 rounded animate-pulse" aria-hidden />
        ) : me ? (
          <div className="flex items-center gap-3">
            <span className="hidden sm:inline text-sm text-slate-600 truncate max-w-[200px]">
              {me.email}
            </span>
            <Link
              href={destinationFor(me.role)}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700"
            >
              Continue →
            </Link>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            {GOOGLE_CLIENT_ID && (
              <GoogleSignInButton
                clientId={GOOGLE_CLIENT_ID}
                onCredential={handleGoogle}
                buttonConfig={{ size: "medium", text: "signin_with" }}
              />
            )}
            <Link
              href="/login"
              className="text-sm text-slate-600 hover:text-indigo-600 px-3 py-2"
            >
              Sign in
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
