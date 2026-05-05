"use client";
import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { exams as examsApi, ApiError } from "@/lib/api";
import type { ExamAttemptOut } from "@/types/api";
import { QuestionCard } from "@/components/exam/QuestionCard";

export default function ExamAttemptPage() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const [attempt, setAttempt] = useState<ExamAttemptOut | null>(null);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [marked, setMarked] = useState<Record<number, boolean>>({});
  const [secondsLeft, setSecondsLeft] = useState(0);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Start the attempt on mount
  useEffect(() => {
    examsApi.startAttempt(slug)
      .then((a) => {
        setAttempt(a);
        const secs = Math.max(0,
          Math.floor((new Date(a.expires_at).getTime() - Date.now()) / 1000));
        setSecondsLeft(secs);
      })
      .catch((e: ApiError) => setError(e.body.message));
    return () => { if (tickRef.current) clearInterval(tickRef.current); };
  }, [slug]);

  // Countdown
  useEffect(() => {
    if (!attempt) return;
    tickRef.current = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1 && attempt) { handleSubmit(); return 0; }
        return s - 1;
      });
    }, 1000);
    return () => { if (tickRef.current) clearInterval(tickRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt?.id]);

  if (error) {
    return (
      <main className="max-w-2xl mx-auto px-6 py-10">
        <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">
          {error}
        </div>
      </main>
    );
  }
  if (!attempt) {
    return <main className="max-w-2xl mx-auto px-6 py-10 text-slate-500">Starting attempt...</main>;
  }

  const q = attempt.questions[index];
  const selected = attempt.user_answers[q.id] ?? null;
  const markedForReview = marked[q.id] ?? false;

  async function handleSelect(letter: string | null) {
    if (!attempt) return;
    const next = { ...attempt, user_answers: { ...attempt.user_answers, [q.id]: letter } };
    setAttempt(next);
    try {
      await examsApi.saveAnswer(attempt.id, {
        question_id: q.id, selected_letter: letter, marked_for_review: markedForReview,
      });
    } catch (e) { setError((e as ApiError).body.message); }
  }

  async function toggleReview() {
    if (!attempt) return;
    const newMarked = { ...marked, [q.id]: !markedForReview };
    setMarked(newMarked);
    try {
      await examsApi.saveAnswer(attempt.id, {
        question_id: q.id, selected_letter: selected,
        marked_for_review: newMarked[q.id],
      });
    } catch (e) { setError((e as ApiError).body.message); }
  }

  async function handleSubmit() {
    if (!attempt || submitting) return;
    setSubmitting(true);
    try {
      const result = await examsApi.submit(attempt.id);
      router.push(`/exams/results/${result.id}`);
    } catch (e) {
      setError((e as ApiError).body.message);
      setSubmitting(false);
    }
  }

  const mm = String(Math.floor(secondsLeft / 60)).padStart(2, "0");
  const ss = String(secondsLeft % 60).padStart(2, "0");
  const lowTime = secondsLeft < 300;

  return (
    <main className="max-w-3xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-wide">
            {attempt.exam_set.name}
          </div>
          <h1 className="text-xl font-bold text-slate-900">CPMAI Mock Exam</h1>
        </div>
        <div className={`px-4 py-2 rounded-lg border tabular-nums font-semibold
                         ${lowTime
                           ? "border-rose-300 bg-rose-50 text-rose-700"
                           : "border-slate-300 bg-white text-slate-900"}`}>
          ⏱ {mm}:{ss}
        </div>
      </div>

      <div className="h-1.5 bg-slate-200 rounded-full mb-6 overflow-hidden">
        <div className="h-full bg-indigo-600 rounded-full transition-all"
             style={{ width: `${((index + 1) / attempt.questions.length) * 100}%` }} />
      </div>

      <QuestionCard
        question={q} index={index} total={attempt.questions.length}
        selected={selected} markedForReview={markedForReview}
        onSelect={handleSelect} onToggleReview={toggleReview}
      />

      <div className="flex items-center justify-between mt-6">
        <button onClick={() => setIndex(Math.max(0, index - 1))}
                disabled={index === 0}
                className="px-4 py-2 text-sm font-medium text-slate-700 bg-white
                           border border-slate-300 rounded-lg disabled:opacity-50">
          ← Previous
        </button>
        {index < attempt.questions.length - 1 ? (
          <button onClick={() => setIndex(index + 1)}
                  className="px-5 py-2 text-sm font-medium text-white bg-indigo-600
                             rounded-lg hover:bg-indigo-700">
            Next →
          </button>
        ) : (
          <button onClick={handleSubmit} disabled={submitting}
                  className="px-5 py-2 text-sm font-medium text-white bg-emerald-600
                             rounded-lg hover:bg-emerald-700 disabled:opacity-50">
            {submitting ? "Submitting..." : "Submit attempt"}
          </button>
        )}
      </div>

      {/* Question palette */}
      <div className="mt-8 bg-white border border-slate-200 rounded-xl p-4">
        <div className="text-xs font-medium text-slate-500 mb-2 uppercase tracking-wide">
          Question palette
        </div>
        <div className="flex flex-wrap gap-1.5">
          {attempt.questions.map((qq, i) => {
            const answered = attempt.user_answers[qq.id] != null;
            const flagged = marked[qq.id];
            const here = i === index;
            return (
              <button
                key={qq.id}
                onClick={() => setIndex(i)}
                className={`w-8 h-8 rounded text-xs font-semibold border
                            ${here ? "ring-2 ring-indigo-400 " : ""}
                            ${flagged
                              ? "bg-amber-100 border-amber-300 text-amber-800"
                              : answered
                                ? "bg-emerald-100 border-emerald-300 text-emerald-800"
                                : "bg-slate-100 border-slate-300 text-slate-600"}`}
              >
                {i + 1}
              </button>
            );
          })}
        </div>
      </div>
    </main>
  );
}
