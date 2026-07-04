"use client";
/**
 * Admin support view of a single exam attempt's results.
 *
 * Reuses the exact same per-question review the aspirant sees (score banner,
 * per-domain breakdown, QuestionResultCard) so an admin can see which questions
 * a candidate passed/failed and guide them on focus areas. Data comes from the
 * admin-gated GET /admin/exams/attempts/{id}/result (server enforces admin).
 *
 * Differs from the aspirant page ((app)/exams/results/[id]) only in chrome and
 * intent: no SiteHeader/Footer (the admin layout provides chrome), no session
 * cache, and none of the "practice/retake" CTAs — the admin isn't the candidate.
 */
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { admin, content as contentApi, errMsg } from "@/lib/api";
import type { SubmitAttemptOut, DomainOut } from "@/types/api";
import { QuestionResultCard } from "@/components/exam/QuestionResultCard";
import { matchesReviewFilters, type ReviewStatus } from "@/lib/examReview";

export default function AdminAttemptResultPage() {
  const { id } = useParams<{ id: string }>();
  const [result, setResult] = useState<SubmitAttemptOut | null>(null);
  const [domains, setDomains] = useState<DomainOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reviewFilter, setReviewFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<ReviewStatus | null>(null);

  useEffect(() => {
    admin.exams.getResult(Number(id))
      .then(setResult)
      .catch((e) => setError(errMsg(e)));
    contentApi.domains().then(setDomains).catch(() => {});
  }, [id]);

  // Resolve a stored domain value to its canonical ECO code (mirrors the
  // aspirant page) so the review filter matches the breakdown rows even for
  // legacy rows that stored a name/slug instead of the code.
  const canon = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of domains) {
      map.set(d.code.toLowerCase(), d.code);
      map.set(d.name.toLowerCase(), d.code);
      map.set(d.slug.toLowerCase(), d.code);
    }
    return (raw: string | null | undefined): string => {
      const key = (raw ?? "").trim();
      if (!key) return "Unassigned";
      return map.get(key.toLowerCase()) ?? key;
    };
  }, [domains]);

  const visibleQuestions = useMemo(() => {
    if (!result) return [];
    return result.questions.filter((q) =>
      matchesReviewFilters(q, { domain: reviewFilter, status: statusFilter, canon })
    );
  }, [result, reviewFilter, statusFilter, canon]);

  const toggleStatus = (s: ReviewStatus) =>
    setStatusFilter((cur) => (cur === s ? null : s));

  const backLink = (
    <Link href="/admin/user-insights"
          className="inline-block text-sm text-indigo-600 hover:underline">
      ← Back to user insights
    </Link>
  );

  if (error) {
    return (
      <main className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
        <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">
          {error}
        </div>
        <div className="mt-4">{backLink}</div>
      </main>
    );
  }
  if (!result) {
    return (
      <main className="max-w-2xl mx-auto px-4 sm:px-6 py-8 text-slate-500">
        Loading…
      </main>
    );
  }

  const minutes = Math.floor(result.time_taken_seconds / 60);
  const seconds = result.time_taken_seconds % 60;
  const labelFor = (code: string) =>
    domains.find((d) => d.code === code)?.name ?? code;

  return (
    <main className="max-w-3xl mx-auto px-4 sm:px-6 py-8">
      <div className="mb-4 flex items-center justify-between gap-3 flex-wrap">
        {backLink}
        <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 border border-slate-200 text-slate-600">
          Admin support view · attempt #{result.id}
        </span>
      </div>

      <div className={`rounded-2xl p-8 mb-6 text-white ${
        result.passed
          ? "bg-gradient-to-br from-emerald-500 to-emerald-700"
          : "bg-gradient-to-br from-rose-500 to-rose-700"
      }`}>
        {result.practice_domain && (
          <div className="text-xs font-medium uppercase tracking-wide opacity-90 mb-1">
            Domain practice · {labelFor(result.practice_domain)}
          </div>
        )}
        <div className="text-sm opacity-90 mb-1">
          {result.passed ? "Passed" : "Did not pass"}
        </div>
        <div className="text-5xl font-bold tabular-nums">{result.score}%</div>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm opacity-90">
          <CountChip n={result.correct_count} label="correct"
                     active={statusFilter === "correct"} onClick={() => toggleStatus("correct")} />
          <CountChip n={result.incorrect_count} label="incorrect"
                     active={statusFilter === "incorrect"} onClick={() => toggleStatus("incorrect")} />
          <CountChip n={result.unanswered_count} label="unanswered"
                     active={statusFilter === "unanswered"} onClick={() => toggleStatus("unanswered")} />
          <span className="ml-1">Time: {minutes}m {seconds}s</span>
        </div>
        <div className="text-xs opacity-75 mt-1">Tap a count to filter the review below.</div>
      </div>

      <section className="bg-white rounded-xl border border-slate-200 p-6 mb-6">
        <div className="flex items-baseline justify-between mb-1">
          <h2 className="font-semibold text-slate-900">Performance by Domain</h2>
          {reviewFilter && (
            <button onClick={() => setReviewFilter(null)}
                    className="text-xs text-indigo-600 hover:underline">
              Clear filter
            </button>
          )}
        </div>
        <p className="text-xs text-slate-500 mb-4">
          The CPMAI exam is scored by domain. Click <strong>Review</strong> to
          read just that domain's questions below — use the weakest domains to
          guide the candidate on where to focus.
        </p>
        <div className="space-y-4">
          {result.by_domain.map((d) => {
            const color = d.percent >= 70 ? "bg-emerald-500"
              : d.percent >= 50 ? "bg-amber-500" : "bg-rose-500";
            const active = reviewFilter === d.domain;
            return (
              <div key={d.domain}
                   className={`rounded-lg border p-3 ${
                     active ? "border-indigo-300 bg-indigo-50/40" : "border-slate-100"
                   }`}>
                <div className="flex justify-between text-sm mb-1 gap-3">
                  <span className="font-medium text-slate-700">{d.domain_name}</span>
                  <span className="text-slate-500 tabular-nums whitespace-nowrap">
                    {d.correct} / {d.total} · {d.percent}%
                  </span>
                </div>
                <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div className={`h-full ${color}`} style={{ width: `${d.percent}%` }} />
                </div>
                <div className="flex gap-2 mt-2.5">
                  <button
                    onClick={() => setReviewFilter(active ? null : d.domain)}
                    className="text-xs px-2.5 py-1 rounded border border-slate-300
                               text-slate-700 hover:bg-slate-50">
                    {active ? "Reviewing ↓" : "Review"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section>
        <h2 className="font-semibold text-slate-900 text-lg mb-2">
          Question-by-question review
        </h2>
        <p className="text-sm text-slate-600 mb-4">
          For each question: the correct answer, why it's correct, and (if the
          candidate chose differently) why their choice was wrong.
        </p>

        {/* Domain filter chips — mirror the breakdown above. */}
        {result.by_domain.length > 1 && (
          <div className="flex flex-wrap gap-1.5 mb-5">
            <button onClick={() => setReviewFilter(null)}
                    className={`text-xs px-2.5 py-1 rounded-full border ${
                      reviewFilter === null
                        ? "bg-indigo-600 text-white border-indigo-600"
                        : "bg-white text-slate-600 border-slate-300 hover:bg-slate-50"
                    }`}>
              All ({result.questions.length})
            </button>
            {result.by_domain.map((d) => (
              <button key={d.domain} onClick={() => setReviewFilter(d.domain)}
                      className={`text-xs px-2.5 py-1 rounded-full border ${
                        reviewFilter === d.domain
                          ? "bg-indigo-600 text-white border-indigo-600"
                          : "bg-white text-slate-600 border-slate-300 hover:bg-slate-50"
                      }`}>
                {d.domain_name} ({d.total})
              </button>
            ))}
          </div>
        )}

        {(statusFilter || reviewFilter) && (
          <div className="text-xs text-slate-600 mb-4 flex items-center gap-2 flex-wrap">
            <span>Showing {visibleQuestions.length} of {result.questions.length}</span>
            {statusFilter && (
              <span className="px-2 py-0.5 rounded-full bg-slate-100 border border-slate-200 capitalize">
                {statusFilter}
              </span>
            )}
            {reviewFilter && (
              <span className="px-2 py-0.5 rounded-full bg-slate-100 border border-slate-200">
                {labelFor(reviewFilter)}
              </span>
            )}
            <button onClick={() => { setStatusFilter(null); setReviewFilter(null); }}
                    className="text-indigo-600 hover:underline">
              Clear filters
            </button>
          </div>
        )}

        <div className="space-y-5">
          {visibleQuestions.length === 0 ? (
            <p className="text-sm text-slate-500 bg-white border border-slate-200 rounded-xl p-6 text-center">
              No questions match this filter.
            </p>
          ) : visibleQuestions.map((q, i) => (
            <QuestionResultCard key={q.id} result={q} index={i} />
          ))}
        </div>
      </section>

      <div className="mt-10">{backLink}</div>
    </main>
  );
}

/** A clickable count in the score banner that filters the review by outcome.
 *  Renders as plain text (non-interactive) when the count is zero. */
function CountChip({ n, label, active, onClick }: {
  n: number; label: string; active: boolean; onClick: () => void;
}) {
  if (n === 0) return <span className="opacity-60">{n} {label}</span>;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded px-2 py-0.5 transition ${
        active
          ? "bg-white/25 font-semibold"
          : "hover:bg-white/15 underline-offset-4 hover:underline"
      }`}
    >
      {n} {label}
    </button>
  );
}
