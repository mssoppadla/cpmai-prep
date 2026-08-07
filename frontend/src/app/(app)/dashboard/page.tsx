"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  auth, content as contentApi, exams as examsApi, lmsPublic, errMsg,
} from "@/lib/api";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import type {
  AttemptHistoryOut, EnrollmentOut, ExamSetSummaryOut, LandingCopy,
  UserDashboardOut,
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

      {/* My courses — enrolled courses with resume + progress */}
      <MyCoursesSection />

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
 * My courses — the learner's active enrollments with an overall progress
 * bar (server-computed: completed lessons / published lessons) and a
 * "Completed" badge. Clicking a card jumps back into the course, where the
 * lesson player resumes each video from its last saved position.
 */
function MyCoursesSection() {
  const [courses, setCourses] = useState<EnrollmentOut[] | null>(null);

  useEffect(() => {
    lmsPublic.myEnrollments().then(setCourses).catch(() => setCourses([]));
  }, []);

  // Resolve quietly; render nothing while loading and nothing if the learner
  // has no enrolled courses (keeps the dashboard uncluttered for exam-only users).
  if (courses === null || courses.length === 0) return null;

  return (
    <section className="max-w-5xl mx-auto px-6 pb-8">
      <h2 className="text-lg font-semibold text-slate-900 mb-1">
        Your courses
      </h2>
      <p className="text-sm text-slate-500 mb-3">
        Pick up where you left off — videos resume from where you paused.
      </p>

      <div className="grid sm:grid-cols-2 gap-4">
        {courses.map((c) => {
          const pct = c.progress_percent ?? 0;
          const done = c.completed_at != null;
          const href = c.course_slug ? `/courses/${c.course_slug}` : "/courses";
          return (
            <Link
              key={c.id}
              href={href}
              className="block bg-white rounded-xl border border-slate-200 p-5 hover:border-indigo-300 hover:shadow-sm transition"
            >
              <div className="flex items-start justify-between gap-2 mb-3">
                <h3 className="font-semibold text-slate-900">
                  {c.course_title ?? "Course"}
                </h3>
                {done && (
                  <span className="shrink-0 text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                    Completed
                  </span>
                )}
              </div>
              <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
                <div
                  className={`h-full rounded-full ${done ? "bg-emerald-500" : "bg-indigo-600"}`}
                  style={{ width: `${pct}%` }}
                  role="progressbar"
                  aria-valuenow={pct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                />
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                <span>
                  {c.lessons_completed ?? 0} / {c.lessons_total ?? 0} lessons
                </span>
                <span className="font-medium text-indigo-600 tabular-nums">{pct}%</span>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

/**
 * Exam history — drafts and submitted results, kept strictly apart.
 *
 * Per set the learner sees up to two rows:
 *   - a DRAFT row (only while a live, unexpired, unsubmitted sitting
 *     exists) — always opens exam-taking mode to continue it;
 *   - the latest SUBMITTED row — always opens the results view.
 * Attempts the clock finished get an explicit "Auto-submitted — time
 * expired" label so they're never mistaken for drafts.
 *
 * The 🗑 on a row opens the attempts-manager window for that set: every
 * instance (drafts + all past results) with a View link each and
 * multi-select delete — replacing the old single-delete that looked
 * like it "didn't work" when the next-older attempt surfaced in place
 * of the deleted one.
 */
function ExamHistorySection() {
  const [attempts, setAttempts] = useState<AttemptHistoryOut[] | null>(null);
  // Slug of the set whose attempts-manager window is open; null = closed.
  const [manageSlug, setManageSlug] = useState<string | null>(null);

  useEffect(() => {
    examsApi.listAttempts().then(setAttempts).catch(() => setAttempts([]));
  }, []);

  const drafts = useMemo(
    () => (attempts ?? []).filter((a) => a.status === "in_progress"),
    [attempts]);

  // Collapse submitted attempts to the single most-recent per exam set
  // (a domain-practice run is its own "set" so it doesn't hide the
  // full-set result). The manager window shows the rest.
  const latest = useMemo(() => {
    const byKey = new Map<string, AttemptHistoryOut>();
    for (const a of attempts ?? []) {
      if (a.status !== "submitted") continue;
      const key = `${a.exam_set_slug ?? a.exam_set_name ?? "set"}::${a.practice_domain ?? ""}`;
      const prev = byKey.get(key);
      if (!prev || new Date(a.submitted_at ?? 0) > new Date(prev.submitted_at ?? 0)) {
        byKey.set(key, a);
      }
    }
    return [...byKey.values()].sort(
      (x, y) => +new Date(y.submitted_at ?? 0) - +new Date(x.submitted_at ?? 0),
    );
  }, [attempts]);

  if (attempts === null) return null; // resolve quietly; no flash

  const manageAttempts = manageSlug === null ? [] :
    attempts.filter((a) => a.exam_set_slug === manageSlug);

  return (
    <section className="max-w-5xl mx-auto px-6 pb-8">
      <h2 className="text-lg font-semibold text-slate-900 mb-1">
        Your exam history
      </h2>
      <p className="text-sm text-slate-500 mb-3">
        Drafts you can continue, and your most recent result for each set.
      </p>

      {/* Draft rows — rendered ONLY while a live draft exists; opening one
          always resumes exam-taking mode. ?resume=1 skips the
          continue-or-discard prompt (this click IS the continue choice). */}
      {drafts.length > 0 && (
        <div className="bg-white rounded-xl border border-amber-200 divide-y divide-amber-100 overflow-hidden mb-3">
          {drafts.map((a) => (
            <Link
              key={a.id}
              href={`/exams/${a.exam_set_slug}${a.practice_domain
                ? `?domain=${encodeURIComponent(a.practice_domain)}&resume=1`
                : "?resume=1"}`}
              className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-amber-50"
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
                <div className="text-xs text-amber-700 mt-0.5">
                  Draft in progress — your answers so far are saved
                  {/* Paused-clock budget — the timer only runs while the
                      exam screen is open, so show duration, not a
                      wall-clock deadline. */}
                  {a.remaining_seconds != null && a.remaining_seconds > 0 && (
                    <> · {Math.floor(a.remaining_seconds / 60)}m {a.remaining_seconds % 60}s left (timer paused)</>
                  )}
                </div>
              </div>
              <span className="text-xs font-semibold text-white bg-indigo-600 rounded px-2.5 py-1 shrink-0">
                Resume →
              </span>
            </Link>
          ))}
        </div>
      )}

      {latest.length === 0 && drafts.length === 0 && (
        <p className="text-sm text-slate-500 bg-white border border-slate-200 rounded-xl p-5">
          No completed exams yet — finish a set and your result will appear here,
          so you can come back to your domain breakdown anytime.
        </p>
      )}
      {latest.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 divide-y divide-slate-100 overflow-hidden">
          {latest.map((a) => {
            const dt = a.submitted_at ? new Date(a.submitted_at) : null;
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
                    {a.auto_submitted && (
                      <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-300"
                            title="The exam clock ran out; everything answered was scored, the rest counted as unanswered">
                        Auto-submitted — time expired
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500 mt-0.5">
                    {dt && <>{dt.toLocaleDateString()}{" "}
                    {dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    {" · "}</>}{a.correct_count}/{a.total_questions} correct
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
                  <button
                    onClick={(e) => {
                      // Row is a Link — keep the click from navigating.
                      e.preventDefault(); e.stopPropagation();
                      setManageSlug(a.exam_set_slug);
                    }}
                    title="Manage all attempts for this set (view / remove)"
                    aria-label={`Manage attempts on ${a.exam_set_name ?? "exam"}`}
                    className="p-1.5 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50"
                  >
                    🗑
                  </button>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {manageSlug !== null && (
        <AttemptsManagerModal
          slug={manageSlug}
          attempts={manageAttempts}
          onClose={() => setManageSlug(null)}
          onDeleted={(ids) => {
            setAttempts((prev) =>
              prev?.filter((a) => !ids.includes(a.id)) ?? prev);
          }}
        />
      )}
    </section>
  );
}

/**
 * Attempts-manager window for one set: every attempt (drafts + results)
 * with View per row and multi-select delete. Opened from the 🗑 on a
 * history row so "delete" always shows the full picture instead of
 * silently revealing the next-older attempt.
 */
function AttemptsManagerModal({ slug, attempts, onClose, onDeleted }: {
  slug: string;
  attempts: AttemptHistoryOut[];
  onClose: () => void;
  onDeleted: (ids: number[]) => void;
}) {
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setName = attempts[0]?.exam_set_name ?? slug;

  function toggle(id: number) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function deleteSelected() {
    if (checked.size === 0) return;
    if (!window.confirm(
      `Remove ${checked.size} attempt${checked.size === 1 ? "" : "s"} from your history? `
      + "They disappear from your dashboard and results — you can't undo this.")) return;
    setBusy(true); setError(null);
    const deleted: number[] = [];
    try {
      for (const id of checked) {
        await examsApi.deleteAttempt(id);
        deleted.push(id);
      }
    } catch (e) {
      setError(`Some deletions failed: ${errMsg(e)}`);
    } finally {
      if (deleted.length > 0) onDeleted(deleted);
      setChecked(new Set());
      setBusy(false);
      if (deleted.length === attempts.length || attempts.length - deleted.length === 0) onClose();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/50" onClick={onClose} aria-hidden />
      <div className="relative bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-2xl max-h-[80vh] flex flex-col"
           role="dialog" aria-modal="true" aria-label={`All attempts for ${setName}`}>
        <div className="flex items-center justify-between p-4 border-b border-slate-200">
          <div>
            <h3 className="font-semibold text-slate-900">All attempts — {setName}</h3>
            <p className="text-xs text-slate-500">
              View any attempt, or select several to delete.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close"
                  className="p-1.5 rounded text-slate-500 hover:bg-slate-100">✕</button>
        </div>

        {error && (
          <div className="mx-4 mt-3 px-3 py-2 rounded bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-4">
          {attempts.length === 0 ? (
            <p className="text-sm text-slate-500">No attempts left for this set.</p>
          ) : (
            <>
            <label className="flex items-center gap-3 px-3 py-2 mb-2 text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded-lg cursor-pointer">
              <input
                type="checkbox"
                checked={checked.size === attempts.length && attempts.length > 0}
                ref={(el) => {
                  // Indeterminate look when some-but-not-all are picked.
                  if (el) el.indeterminate =
                    checked.size > 0 && checked.size < attempts.length;
                }}
                onChange={() =>
                  setChecked(checked.size === attempts.length
                    ? new Set()
                    : new Set(attempts.map((a) => a.id)))}
                aria-label="Select all attempts"
                className="w-4 h-4 accent-indigo-600"
              />
              Select all ({attempts.length})
            </label>
            <ul className="divide-y divide-slate-100 border border-slate-200 rounded-lg overflow-hidden">
              {attempts.map((a) => {
                const isDraft = a.status === "in_progress";
                const dt = a.submitted_at ? new Date(a.submitted_at) : null;
                return (
                  <li key={a.id} className="flex items-center gap-3 px-3 py-2.5 bg-white">
                    <input
                      type="checkbox"
                      checked={checked.has(a.id)}
                      onChange={() => toggle(a.id)}
                      aria-label={`Select attempt from ${dt ? dt.toLocaleString() : "draft"}`}
                      className="w-4 h-4 accent-indigo-600"
                    />
                    <div className="flex-1 min-w-0 text-sm">
                      {isDraft ? (
                        <span className="font-medium text-amber-700">
                          Draft in progress
                          {a.practice_domain && ` · Practice: ${a.practice_domain}`}
                        </span>
                      ) : (
                        <span className="text-slate-900">
                          {dt?.toLocaleDateString()}{" "}
                          {dt?.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                          {" · "}
                          <span className={a.passed ? "text-emerald-700 font-semibold" : "text-rose-600 font-semibold"}>
                            {a.score}%
                          </span>
                          {" · "}{a.correct_count}/{a.total_questions} correct
                          {a.practice_domain && ` · Practice: ${a.practice_domain}`}
                          {a.auto_submitted && (
                            <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-300">
                              Auto-submitted — time expired
                            </span>
                          )}
                        </span>
                      )}
                    </div>
                    {isDraft ? (
                      <Link
                        href={`/exams/${a.exam_set_slug}${a.practice_domain
                          ? `?domain=${encodeURIComponent(a.practice_domain)}&resume=1`
                          : "?resume=1"}`}
                        className="text-xs font-semibold text-white bg-indigo-600 rounded px-2.5 py-1 shrink-0"
                      >
                        Resume →
                      </Link>
                    ) : (
                      <Link href={`/exams/results/${a.id}`}
                            className="text-sm text-indigo-600 hover:underline shrink-0">
                        View
                      </Link>
                    )}
                  </li>
                );
              })}
            </ul>
            </>
          )}
        </div>

        <div className="flex items-center justify-between p-4 border-t border-slate-200">
          <span className="text-xs text-slate-500">
            {checked.size} selected
          </span>
          <div className="flex gap-2">
            <button onClick={onClose}
                    className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50">
              Close
            </button>
            <button
              onClick={() => void deleteSelected()}
              disabled={busy || checked.size === 0}
              className="px-4 py-2 text-sm font-medium text-white bg-rose-600 rounded-lg hover:bg-rose-700 disabled:opacity-50"
            >
              {busy ? "Deleting…" : `Delete selected (${checked.size})`}
            </button>
          </div>
        </div>
      </div>
    </div>
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
