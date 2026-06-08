"use client";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { exams as examsApi, content as contentApi, ApiError } from "@/lib/api";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import type { SubmitAttemptOut, DomainOut } from "@/types/api";
import { QuestionResultCard } from "@/components/exam/QuestionResultCard";
import {
  matchesReviewFilters, type ReviewStatus,
} from "@/lib/examReview";

export default function ResultsPage() {
  const { id } = useParams<{ id: string }>();
  const [result, setResult] = useState<SubmitAttemptOut | null>(null);
  const [domains, setDomains] = useState<DomainOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Which domain the question-by-question review is filtered to. null = all.
  const [reviewFilter, setReviewFilter] = useState<string | null>(null);
  // Outcome filter, toggled from the score summary. null = all.
  const [statusFilter, setStatusFilter] = useState<ReviewStatus | null>(null);

  useEffect(() => {
    // Try session cache first (fast), then fall back to API (cold load).
    if (typeof window !== "undefined") {
      const cached = window.sessionStorage.getItem(`result:${id}`);
      if (cached) {
        try { setResult(JSON.parse(cached)); } catch {}
      }
    }
    examsApi.getResult(Number(id))
      .then((r) => {
        setResult(r);
        try {
          window.sessionStorage.setItem(`result:${id}`, JSON.stringify(r));
        } catch {}
      })
      .catch((e: ApiError) => setError(e.body.message));
    contentApi.domains().then(setDomains).catch(() => {});
  }, [id]);

  // Resolve a stored domain value to its canonical ECO code, mirroring the
  // backend so the review filter matches the breakdown rows even for legacy
  // rows that stored a name/slug instead of the code.
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

  if (error) {
    return (
      <>
        <SiteHeader active="exams" />
        <main className="max-w-2xl mx-auto px-4 sm:px-6 py-8 sm:py-10">
          <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">
            {error}
          </div>
          <Link href="/exams" className="inline-block mt-4 text-indigo-600 hover:underline">
            ← Back to exam sets
          </Link>
        </main>
        <SiteFooter />
      </>
    );
  }
  if (!result) {
    return (
      <>
        <SiteHeader active="exams" />
        <main className="max-w-2xl mx-auto px-4 sm:px-6 py-8 sm:py-10 text-slate-500">
          Loading...
        </main>
        <SiteFooter />
      </>
    );
  }

  const minutes = Math.floor(result.time_taken_seconds / 60);
  const seconds = result.time_taken_seconds % 60;
  const labelFor = (code: string) =>
    domains.find((d) => d.code === code)?.name ?? code;

  return (
    <>
      <SiteHeader active="exams" />
      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-10">
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
          {result.passed ? "🎉 You passed!" : "Keep practicing — it'll help you ace the exam."}
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
          read just that domain's questions below, or{" "}
          <strong>Practice</strong> to retry only that domain.
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
                  {d.practiceable && result.exam_set_slug && (
                    <Link
                      href={`/exams/${result.exam_set_slug}?domain=${encodeURIComponent(d.domain)}`}
                      className="text-xs px-2.5 py-1 rounded border border-indigo-300
                                 text-indigo-700 bg-indigo-50 hover:bg-indigo-100">
                      Practice this domain →
                    </Link>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section>
        <div className="flex items-center justify-between mb-2 gap-3 flex-wrap">
          <h2 className="font-semibold text-slate-900 text-lg">
            Question-by-question review
          </h2>
          {result.exam_set_slug && (
            <Link href={`/exams/${result.exam_set_slug}`}
                  className="text-sm font-medium text-indigo-600 hover:underline">
              ↻ Retake full exam
            </Link>
          )}
        </div>
        <p className="text-sm text-slate-600 mb-4">
          For each question: the correct answer, why it's correct, and (if you
          chose differently) why your choice was wrong.
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

      <div className="mt-10 text-center">
        <Link href="/exams" className="px-6 py-3 bg-indigo-600 text-white font-semibold
                                       rounded-lg hover:bg-indigo-700 inline-block">
          Try another set →
        </Link>
      </div>
      </main>
      <SiteFooter />
    </>
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
