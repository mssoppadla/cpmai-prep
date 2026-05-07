"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth, content as contentApi, exams as examsApi, errMsg } from "@/lib/api";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import type {
  ExamSetSummaryOut, LandingCopy, UserDashboardOut,
} from "@/types/api";

const UPSELL_FALLBACK: Pick<LandingCopy, "premium_upsell_title" | "premium_upsell_body"> = {
  premium_upsell_title: "Get the full bank",
  premium_upsell_body:
    "Premium unlocks all advanced sets, AI tutor with extended quota, and detailed performance analytics.",
};

/**
 * Learner dashboard — shown after a user (role=`user`) signs in.
 *
 * Pulls subscription status, then renders:
 *   - Welcome message with name
 *   - Subscription badge (Free / Active plan)
 *   - List of exam sets with locked/unlocked state based on subscription
 *   - Upgrade CTA when not subscribed
 */
export default function LearnerDashboard() {
  const router = useRouter();
  const [data, setData] = useState<UserDashboardOut | null>(null);
  const [sets, setSets] = useState<ExamSetSummaryOut[] | null>(null);
  const [upsell, setUpsell] = useState(UPSELL_FALLBACK);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [d, s, copy] = await Promise.all([
          auth.dashboard(),
          examsApi.listSets(),
          contentApi.landing().catch(() => null),  // best-effort
        ]);
        if (cancelled) return;
        setData(d);
        setSets(s);
        if (copy) {
          setUpsell({
            premium_upsell_title: copy.premium_upsell_title,
            premium_upsell_body:  copy.premium_upsell_body,
          });
        }
        // If an admin somehow lands here, kick them to the admin console.
        if (d.user.role === "admin" || d.user.role === "super_admin") {
          router.replace("/admin");
        }
      } catch (e) {
        if (cancelled) return;
        // No valid token → bounce to login
        const ok = await auth.refresh();
        if (ok) {
          try {
            const d = await auth.dashboard();
            const s = await examsApi.listSets();
            if (!cancelled) { setData(d); setSets(s); }
            return;
          } catch {}
        }
        setErr(errMsg(e));
        setTimeout(() => router.replace("/login?next=/dashboard"), 800);
      }
    })();
    return () => { cancelled = true; };
  }, [router]);

  if (err) {
    return (
      <>
        <SiteHeader />
        <main className="min-h-[40vh] max-w-3xl mx-auto p-8 text-rose-600">
          {err}
        </main>
        <SiteFooter />
      </>
    );
  }
  if (!data || !sets) {
    return (
      <>
        <SiteHeader />
        <main className="min-h-[40vh] max-w-3xl mx-auto p-8 text-slate-500">
          Loading…
        </main>
        <SiteFooter />
      </>
    );
  }

  const sub = data.subscription;
  const displayName = data.user.name || data.user.email.split("@")[0];

  // Group sets by accessibility for clearer UI.
  const freeSets    = sets.filter(s => !s.is_premium);
  const premiumSets = sets.filter(s => s.is_premium);
  const canPremium  = sub.active;

  return (
    <>
      <SiteHeader />
      <main className="min-h-screen bg-slate-50">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between text-sm border-b border-slate-200 bg-white">
          <div className="text-slate-500">
            <span className="font-semibold text-slate-700">Learner Dashboard</span>
            <span className="hidden sm:inline"> · {data.user.email}</span>
          </div>
          <button
            onClick={async () => { await auth.logout(); router.push("/"); }}
            className="text-indigo-600 hover:underline"
          >
            Sign out
          </button>
        </div>

      <section className="max-w-5xl mx-auto px-6 py-8">
        <h1 className="text-2xl font-bold text-slate-900">
          Welcome, {displayName}
        </h1>
        <div className="mt-2 flex items-center gap-2 flex-wrap">
          {sub.active ? (
            <>
              <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                Active plan: {sub.plan ?? "premium"}
              </span>
              {sub.current_period_end && (
                <span className="text-xs text-slate-500">
                  renews / expires {new Date(sub.current_period_end).toLocaleDateString()}
                </span>
              )}
            </>
          ) : (
            <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-700 border border-slate-200">
              Free plan
            </span>
          )}
          {data.has_google && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs text-slate-500 border border-slate-200">
              Signed in with Google
            </span>
          )}
        </div>
      </section>

      {/* Free exam sets — always available */}
      <section className="max-w-5xl mx-auto px-6 pb-8">
        <h2 className="text-lg font-semibold text-slate-900 mb-3">
          Free practice sets
        </h2>
        {freeSets.length === 0 ? (
          <p className="text-sm text-slate-500">No free sets available yet.</p>
        ) : (
          <div className="grid sm:grid-cols-2 gap-4">
            {freeSets.map((s) => <SetCard key={s.id} set={s} accessible />)}
          </div>
        )}
      </section>

      {/* Premium exam sets — gated */}
      <section className="max-w-5xl mx-auto px-6 pb-12">
        <div className="flex items-end justify-between mb-3">
          <h2 className="text-lg font-semibold text-slate-900">
            Premium exam sets
          </h2>
          {!canPremium && (
            <Link
              href="/pricing"
              className="text-sm text-indigo-600 font-medium hover:underline"
            >
              Upgrade to unlock →
            </Link>
          )}
        </div>
        {premiumSets.length === 0 ? (
          <p className="text-sm text-slate-500">No premium sets yet.</p>
        ) : (
          <div className="grid sm:grid-cols-2 gap-4">
            {premiumSets.map((s) => (
              <SetCard key={s.id} set={s} accessible={canPremium} />
            ))}
          </div>
        )}

        {!canPremium && (
          <div className="mt-6 bg-gradient-to-br from-indigo-50 to-purple-50 border border-indigo-200 rounded-xl p-5 flex items-start gap-4">
            <div className="flex-1">
              <div className="text-sm font-semibold text-indigo-900 mb-1">
                {upsell.premium_upsell_title}
              </div>
              <p className="text-sm text-indigo-800">
                {upsell.premium_upsell_body}
              </p>
            </div>
            <Link
              href="/pricing"
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700"
            >
              View plans
            </Link>
          </div>
        )}
      </section>
      </main>
      <SiteFooter />
    </>
  );
}

function SetCard({ set, accessible }: {
  set: ExamSetSummaryOut; accessible: boolean;
}) {
  const inner = (
    <div className={`bg-white rounded-xl border p-5 transition ${
      accessible
        ? "border-slate-200 hover:border-indigo-300 hover:shadow-sm"
        : "border-slate-200 opacity-75"
    }`}>
      <div className="flex items-center gap-2 mb-2">
        <h3 className="font-semibold text-slate-900">{set.name}</h3>
        {set.is_premium && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-200">
            premium
          </span>
        )}
      </div>
      {set.description && (
        <p className="text-sm text-slate-600 line-clamp-2 mb-3">{set.description}</p>
      )}
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>
          {set.question_count} questions · {set.time_limit_minutes} min · pass {set.passing_score}%
        </span>
        <span className="font-medium text-indigo-600">
          {accessible ? "Start →" : "🔒 Locked"}
        </span>
      </div>
    </div>
  );
  return accessible ? (
    <Link href={`/exams/${set.slug}`} className="block">{inner}</Link>
  ) : (
    inner
  );
}
