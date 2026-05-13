"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { auth, content, exams as examsApi, errMsg } from "@/lib/api";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import type { ExamSetSummaryOut, UserOut } from "@/types/api";
import { ExamSetCard } from "@/components/exam/ExamSetCard";

// Default copy for the anonymous-state banner. Used while /content/landing
// is in flight, AND as a fallback if the API is unreachable. Kept in sync
// with the seeded value in backend/seeds/default_settings.json so a
// freshly-built frontend looks the same regardless of seed state.
const DEFAULT_ANON_BANNER =
  "You're not signed in. Free sets are open — start one anonymously and " +
  "you'll see your result immediately (just not saved to a dashboard). " +
  "Sign in to save attempts; subscribe to unlock premium sets.";

/**
 * Public Mock Exams list. Reachable by anyone — including visitors who
 * just submitted the landing-page form and got bounced here. So the
 * header must offer a clear path forward (sign in / pricing / home),
 * not just dump them into a list of sets that all need authentication.
 */
export default function ExamSetsPage() {
  const [sets, setSets] = useState<ExamSetSummaryOut[] | null>(null);
  const [me, setMe] = useState<UserOut | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  // Admin-editable anonymous-state banner. Pulled from /content/landing
  // so non-engineering admins can rephrase without a redeploy. Falls
  // back to DEFAULT_ANON_BANNER if the API is unreachable.
  const [anonBanner, setAnonBanner] = useState(DEFAULT_ANON_BANNER);

  useEffect(() => {
    examsApi.listSets()
      .then(setSets)
      .catch((e) => setError(errMsg(e)));
    auth.me().then(setMe).catch(() => setMe(null));
    content.landing()
      .then((c) => {
        const v = c.exams_anonymous_banner?.trim();
        if (v) setAnonBanner(v);
      })
      .catch(() => { /* keep default */ });
  }, []);

  return (
    <>
      <SiteHeader active="exams" />
      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-8 sm:py-10">
      <header className="mb-6">
        <h1 className="text-3xl font-bold text-slate-900">Mock Exams</h1>
        <p className="text-slate-600 mt-2">
          Pick a set to start. Each set is a complete CPMAI exam simulation.
        </p>
      </header>

      {/* For unauth visitors who just came from the landing form: spell
          out that an account is needed before starting an attempt, with
          one-click paths forward. */}
      {me === null && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-4 mb-6 flex flex-col sm:flex-row sm:items-center gap-3">
          <div className="flex-1 text-sm text-indigo-900">
            {/* Whole banner copy is admin-editable now (was hardcoded
                before). The bold "You're not signed in." opener is
                folded INTO the configured string so admins can change
                tone or remove the bold-then-explanation pattern as
                they see fit. Server caps the length at 1000 chars. */}
            {anonBanner}
          </div>
          <div className="flex gap-2 flex-shrink-0">
            <Link
              href="/login?next=%2Fexams"
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700"
            >
              Sign in
            </Link>
            <Link
              href="/pricing"
              className="px-4 py-2 bg-white text-indigo-700 text-sm font-medium border border-indigo-200 rounded-lg hover:bg-indigo-100"
            >
              Pricing
            </Link>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg mb-6">
          {error}
        </div>
      )}
      {!sets ? (
        <div className="text-slate-500">Loading...</div>
      ) : sets.length === 0 ? (
        <div className="text-slate-500">No exam sets available yet.</div>
      ) : (
        <div className="grid sm:grid-cols-2 gap-4">
          {sets.map((s) => <ExamSetCard key={s.id} set={s} />)}
        </div>
      )}
      </main>
      <SiteFooter />
    </>
  );
}
