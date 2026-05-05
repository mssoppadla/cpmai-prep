"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { exams as examsApi, ApiError } from "@/lib/api";
import type { SubmitAttemptOut } from "@/types/api";
import { QuestionResultCard } from "@/components/exam/QuestionResultCard";

export default function ResultsPage() {
  const { id } = useParams<{ id: string }>();
  const [result, setResult] = useState<SubmitAttemptOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Re-submit is idempotent (server returns 409 if already submitted),
    // so we fetch via a dedicated GET in production. For this scaffold,
    // we cache on the attempt page; if a user lands here cold, fall back
    // to error state and ask them to retake.
    const cached = typeof window !== "undefined"
      ? window.sessionStorage.getItem(`result:${id}`) : null;
    if (cached) {
      setResult(JSON.parse(cached) as SubmitAttemptOut);
      return;
    }
    // TODO: implement GET /exams/attempts/{id}/result for cold loads.
    setError("Result not in session. Take the exam again to view results.");
  }, [id]);

  if (error) {
    return (
      <main className="max-w-2xl mx-auto px-6 py-10">
        <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">
          {error}
        </div>
        <Link href="/exams" className="inline-block mt-4 text-indigo-600 hover:underline">
          ← Back to exam sets
        </Link>
      </main>
    );
  }
  if (!result) {
    return <main className="max-w-2xl mx-auto px-6 py-10 text-slate-500">Loading...</main>;
  }

  const minutes = Math.floor(result.time_taken_seconds / 60);
  const seconds = result.time_taken_seconds % 60;

  return (
    <main className="max-w-3xl mx-auto px-6 py-10">
      {/* Score banner */}
      <div className={`rounded-2xl p-8 mb-8 text-white ${
        result.passed
          ? "bg-gradient-to-br from-emerald-500 to-emerald-700"
          : "bg-gradient-to-br from-rose-500 to-rose-700"
      }`}>
        <div className="text-sm opacity-90 mb-1">
          {result.passed ? "🎉 You passed!" : "Keep practicing — you're getting closer."}
        </div>
        <div className="text-5xl font-bold tabular-nums">{result.score}%</div>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm opacity-90">
          <span>{result.correct_count} correct</span>
          <span>{result.incorrect_count} incorrect</span>
          <span>{result.unanswered_count} unanswered</span>
          <span>Time: {minutes}m {seconds}s</span>
        </div>
      </div>

      {/* Per-phase breakdown */}
      <section className="bg-white rounded-xl border border-slate-200 p-6 mb-8">
        <h2 className="font-semibold text-slate-900 mb-4">Performance by CPMAI Phase</h2>
        <div className="space-y-3">
          {result.by_phase.map((p) => {
            const color = p.percent >= 70 ? "bg-emerald-500"
              : p.percent >= 50 ? "bg-amber-500" : "bg-rose-500";
            return (
              <div key={p.topic_code}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="font-medium text-slate-700">
                    {p.topic_code} — {p.topic_name}
                  </span>
                  <span className="text-slate-500 tabular-nums">
                    {p.correct} / {p.total} · {p.percent}%
                  </span>
                </div>
                <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div className={`h-full ${color}`} style={{ width: `${p.percent}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Per-question review with reasoning */}
      <section>
        <h2 className="font-semibold text-slate-900 mb-4 text-lg">
          Question-by-question review
        </h2>
        <p className="text-sm text-slate-600 mb-5">
          For each question: the correct answer, why it's correct, and (if you chose
          differently) why your choice was wrong.
        </p>
        <div className="space-y-5">
          {result.questions.map((q, i) => (
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
  );
}
