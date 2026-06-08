"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth, content as contentApi, exams as examsApi, errMsg } from "@/lib/api";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import type {
  AttemptHistoryOut, ExamSetSummaryOut, LandingCopy, UserDashboardOut,
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

      {/* Exam history — past attempts persist; revisit domain insights anytime */}
      <ExamHistorySection />

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

      <PrivacySection email={data.user.email} onAfterDelete={() => router.push("/")} />
      </main>
      <SiteFooter />
    </>
  );
}

function PrivacySection({ email, onAfterDelete }: {
  email: string; onAfterDelete: () => void;
}) {
  const [busy, setBusy] = useState<"export" | "delete" | null>(null);
  const [err, setErr]   = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [typed, setTyped] = useState("");

  async function onExport() {
    setBusy("export"); setErr(null);
    try {
      const data = await auth.exportMyData();
      const blob = new Blob([JSON.stringify(data, null, 2)],
                            { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `cpmai-data-${email.split("@")[0]}-${new Date()
        .toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErr(errMsg(e));
    } finally { setBusy(null); }
  }

  async function onConfirmDelete() {
    setBusy("delete"); setErr(null);
    try {
      await auth.deleteMyAccount();
      onAfterDelete();
    } catch (e) {
      setErr(errMsg(e));
      setBusy(null);
    }
  }

  return (
    <section className="max-w-5xl mx-auto px-6 pb-12 border-t border-slate-200 pt-8">
      <h2 className="text-lg font-semibold text-slate-900 mb-1">
        Privacy &amp; data
      </h2>
      <p className="text-sm text-slate-500 mb-4">
        Download everything we have for your account, or permanently
        delete it.
      </p>
      {err && (
        <div className="mb-3 text-sm text-rose-600">{err}</div>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={onExport}
          disabled={!!busy}
          className="px-4 py-2 text-sm font-medium rounded-lg border border-slate-300 text-slate-700 bg-white hover:bg-slate-50 disabled:opacity-60"
        >
          {busy === "export" ? "Preparing…" : "Download my data"}
        </button>
        <button
          type="button"
          onClick={() => { setTyped(""); setConfirmOpen(true); }}
          disabled={!!busy}
          className="px-4 py-2 text-sm font-medium rounded-lg border border-rose-300 text-rose-700 bg-white hover:bg-rose-50 disabled:opacity-60"
        >
          Delete my account
        </button>
      </div>

      {confirmOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 bg-slate-900/60 flex items-center justify-center px-4"
          onClick={() => !busy && setConfirmOpen(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="bg-white rounded-xl shadow-xl max-w-md w-full p-6"
          >
            <h3 className="text-base font-semibold text-slate-900 mb-2">
              Delete your account?
            </h3>
            <p className="text-sm text-slate-600 mb-3">
              This permanently redacts your profile (email, name, sign-in
              credentials) and signs you out. Financial records
              (payments, subscriptions) are retained as required by
              Indian tax law but are no longer linked to a usable account.
              <strong className="text-slate-900"> This cannot be undone.</strong>
            </p>
            <label className="block text-xs text-slate-500 mb-1">
              Type <code className="font-mono text-rose-700">DELETE</code> to confirm
            </label>
            <input
              autoFocus
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm mb-4"
              placeholder="DELETE"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                disabled={!!busy}
                className="px-3 py-2 text-sm rounded-md border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={onConfirmDelete}
                disabled={typed !== "DELETE" || !!busy}
                className="px-3 py-2 text-sm rounded-md bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {busy === "delete" ? "Deleting…" : "Delete account"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

/**
 * Exam history — the learner's past submitted attempts. Each row links back
 * into the full results screen (by-domain breakdown + question review), so a
 * candidate can always return to see which domains they scored high/low on
 * and where to focus. Attempts persist server-side; this just surfaces them.
 */
function ExamHistorySection() {
  const [attempts, setAttempts] = useState<AttemptHistoryOut[] | null>(null);

  useEffect(() => {
    examsApi.listAttempts().then(setAttempts).catch(() => setAttempts([]));
  }, []);

  if (attempts === null) return null; // resolve quietly; no flash

  return (
    <section className="max-w-5xl mx-auto px-6 pb-8">
      <h2 className="text-lg font-semibold text-slate-900 mb-1">
        Your exam history
      </h2>
      <p className="text-sm text-slate-500 mb-3">
        Revisit any past attempt to see which domains you scored high or low on,
        and where to focus next.
      </p>

      {attempts.length === 0 ? (
        <p className="text-sm text-slate-500 bg-white border border-slate-200 rounded-xl p-5">
          No completed exams yet — finish a set and your result will appear here,
          so you can come back to your domain breakdown anytime.
        </p>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 divide-y divide-slate-100 overflow-hidden">
          {attempts.map((a) => {
            const dt = new Date(a.submitted_at);
            const mins = Math.floor(a.time_taken_seconds / 60);
            const secs = a.time_taken_seconds % 60;
            return (
              <Link
                key={a.id}
                href={`/exams/results/${a.id}`}
                className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-slate-50"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium text-slate-900 truncate">
                    {a.exam_set_name ?? "Exam"}
                    {a.practice_domain && (
                      <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200">
                        Practice: {a.practice_domain}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500 mt-0.5">
                    {dt.toLocaleDateString()}{" "}
                    {dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    {" · "}{a.correct_count}/{a.total_questions} correct
                    {" · "}{mins}m {secs}s
                  </div>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span className={`text-lg font-bold tabular-nums ${
                    a.passed ? "text-emerald-700" : "text-rose-600"
                  }`}>
                    {a.score}%
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full border ${
                    a.passed
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : "bg-rose-50 text-rose-700 border-rose-200"
                  }`}>
                    {a.passed ? "Passed" : "Keep practicing"}
                  </span>
                  <span className="text-indigo-600 text-sm hidden sm:inline">View →</span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </section>
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
