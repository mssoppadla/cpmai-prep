"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { exams as examsApi, errMsg } from "@/lib/api";
import type { ExamAttemptOut } from "@/types/api";
import {
  QuestionCard, type OptionAnnotations, type Tool,
} from "@/components/exam/QuestionCard";

type AnnotationsByQ = Record<number, OptionAnnotations>;

/** localStorage key for per-attempt annotations (survives reloads). */
const annKey = (attemptId: number) => `cpmai.exam.annotations.${attemptId}`;
const markKey = (attemptId: number) => `cpmai.exam.marked.${attemptId}`;

export default function ExamAttemptPage() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const [attempt, setAttempt] = useState<ExamAttemptOut | null>(null);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [marked, setMarked] = useState<Record<number, boolean>>({});
  const [annotations, setAnnotations] = useState<AnnotationsByQ>({});
  const [tool, setTool] = useState<Tool>("none");
  const [showReview, setShowReview] = useState(false);
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

        // Restore any per-attempt local state (annotations + marked)
        try {
          const ann = JSON.parse(localStorage.getItem(annKey(a.id)) ?? "{}");
          setAnnotations(ann);
          const mk = JSON.parse(localStorage.getItem(markKey(a.id)) ?? "{}");
          setMarked(mk);
        } catch { /* corrupt JSON — ignore */ }
      })
      .catch((e) => {
        console.error("[exam] start", e);
        setError(errMsg(e));
      });
    return () => { if (tickRef.current) clearInterval(tickRef.current); };
  }, [slug]);

  // Persist local annotations / marked whenever they change.
  useEffect(() => {
    if (!attempt) return;
    localStorage.setItem(annKey(attempt.id), JSON.stringify(annotations));
  }, [annotations, attempt]);
  useEffect(() => {
    if (!attempt) return;
    localStorage.setItem(markKey(attempt.id), JSON.stringify(marked));
  }, [marked, attempt]);

  // Countdown
  useEffect(() => {
    if (!attempt) return;
    tickRef.current = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1 && attempt) { void confirmSubmit(); return 0; }
        return s - 1;
      });
    }, 1000);
    return () => { if (tickRef.current) clearInterval(tickRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt?.id]);

  // Memos must run unconditionally on every render (Rules of Hooks).
  // Compute review-related lists from current state; safe even when
  // attempt is null (we just return empty arrays in that case).
  const reviewIds = useMemo(() =>
    Object.entries(marked).filter(([, v]) => v).map(([k]) => Number(k)),
    [marked]);
  const unansweredCount = useMemo(() => {
    if (!attempt) return 0;
    return attempt.questions.filter(
      (qq) => attempt.user_answers[qq.id] == null
    ).length;
  }, [attempt]);

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
  const qAnnotations = annotations[q.id] ?? {};

  async function handleSelect(letter: string | null) {
    if (!attempt) return;
    const next = { ...attempt, user_answers: { ...attempt.user_answers, [q.id]: letter } };
    setAttempt(next);
    try {
      await examsApi.saveAnswer(attempt.id, {
        question_id: q.id, selected_letter: letter,
        marked_for_review: markedForReview,
      });
    } catch (e) { setError(errMsg(e)); }
  }

  async function toggleReview() {
    if (!attempt) return;
    const next = { ...marked, [q.id]: !markedForReview };
    setMarked(next);
    try {
      await examsApi.saveAnswer(attempt.id, {
        question_id: q.id, selected_letter: selected,
        marked_for_review: next[q.id],
      });
    } catch (e) { setError(errMsg(e)); }
  }

  function annotateOption(letter: string) {
    setAnnotations((all) => {
      const cur = all[q.id] ?? {};
      const existing = cur[letter] ?? null;
      let next = existing;
      if (tool === "eraser") next = null;
      else if (tool === "highlight") next = existing === "highlight" ? null : "highlight";
      else if (tool === "strike")    next = existing === "strike"    ? null : "strike";
      return { ...all, [q.id]: { ...cur, [letter]: next } };
    });
  }

  function attemptSubmit() {
    // Show the review screen first — the user must confirm.
    setShowReview(true);
  }

  async function confirmSubmit() {
    if (!attempt || submitting) return;
    setSubmitting(true);
    try {
      const result = await examsApi.submit(attempt.id);
      // Clear per-attempt local state on successful submit
      try {
        localStorage.removeItem(annKey(attempt.id));
        localStorage.removeItem(markKey(attempt.id));
      } catch { /* ignore */ }
      router.push(`/exams/results/${result.id}`);
    } catch (e) {
      setError(errMsg(e));
      setSubmitting(false);
      setShowReview(false);
    }
  }

  const mm = String(Math.floor(secondsLeft / 60)).padStart(2, "0");
  const ss = String(secondsLeft % 60).padStart(2, "0");
  const lowTime = secondsLeft < 300;

  return (
    <main className="max-w-3xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-wide">
            {attempt.exam_set.name}
          </div>
          <h1 className="text-xl font-bold text-slate-900">CPMAI Mock Exam</h1>
        </div>
        <Toolbox tool={tool} setTool={setTool} />
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
        tool={tool} annotations={qAnnotations}
        onSelect={handleSelect}
        onToggleReview={toggleReview}
        onAnnotate={annotateOption}
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
          <button onClick={attemptSubmit} disabled={submitting}
                  className="px-5 py-2 text-sm font-medium text-white bg-emerald-600
                             rounded-lg hover:bg-emerald-700 disabled:opacity-50">
            {submitting ? "Submitting..." : "Review & submit"}
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
        <div className="text-xs text-slate-500 mt-3 flex flex-wrap gap-x-4 gap-y-1">
          <span><span className="inline-block w-3 h-3 rounded bg-emerald-100 border border-emerald-300 mr-1 align-middle" />answered</span>
          <span><span className="inline-block w-3 h-3 rounded bg-amber-100 border border-amber-300 mr-1 align-middle" />marked for review</span>
          <span><span className="inline-block w-3 h-3 rounded bg-slate-100 border border-slate-300 mr-1 align-middle" />unanswered</span>
        </div>
      </div>

      {showReview && (
        <ReviewModal
          attempt={attempt}
          markedIds={reviewIds}
          unansweredCount={unansweredCount}
          submitting={submitting}
          onJumpTo={(qid) => {
            const i = attempt.questions.findIndex((qq) => qq.id === qid);
            if (i >= 0) setIndex(i);
            setShowReview(false);
          }}
          onCancel={() => setShowReview(false)}
          onConfirm={confirmSubmit}
        />
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Toolbox: highlight / strike / eraser. Click again to deactivate.
// ---------------------------------------------------------------------------
function Toolbox({ tool, setTool }: { tool: Tool; setTool: (t: Tool) => void }) {
  function toggle(t: Exclude<Tool, "none">) {
    setTool(tool === t ? "none" : t);
  }
  const cls = (t: Tool) =>
    `px-3 py-2 text-sm border rounded-lg transition ${
      tool === t
        ? "bg-indigo-600 text-white border-indigo-600"
        : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
    }`;
  return (
    <div className="flex items-center gap-1 bg-white border border-slate-200 rounded-lg p-1"
         role="toolbar" aria-label="Annotation tools">
      <span className="text-xs text-slate-500 px-2">Toolbox</span>
      <button type="button" onClick={() => toggle("highlight")}
              title="Highlight an option (click an option to mark)"
              className={cls("highlight")}>
        <span aria-hidden>🖍</span>
        <span className="sr-only">Highlight</span>
      </button>
      <button type="button" onClick={() => toggle("strike")}
              title="Strike out an option you think is wrong"
              className={cls("strike")}>
        <span aria-hidden>S̶</span>
        <span className="sr-only">Strike</span>
      </button>
      <button type="button" onClick={() => toggle("eraser")}
              title="Click an option to clear its highlight or strike"
              className={cls("eraser")}>
        <span aria-hidden>🧽</span>
        <span className="sr-only">Eraser</span>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ReviewModal: surfaces marked + unanswered questions before final submit.
// ---------------------------------------------------------------------------
interface ReviewModalProps {
  attempt: ExamAttemptOut;
  markedIds: number[];
  unansweredCount: number;
  submitting: boolean;
  onJumpTo: (questionId: number) => void;
  onCancel: () => void;
  onConfirm: () => void;
}
function ReviewModal({
  attempt, markedIds, unansweredCount, submitting,
  onJumpTo, onCancel, onConfirm,
}: ReviewModalProps) {
  const markedQs = attempt.questions.filter((q) => markedIds.includes(q.id));
  return (
    <div className="fixed inset-0 z-50 bg-slate-900/60 flex items-end sm:items-center justify-center p-4"
         onClick={onCancel}>
      <div className="bg-white w-full max-w-lg rounded-xl shadow-xl"
           onClick={(e) => e.stopPropagation()}>
        <div className="p-5 border-b border-slate-200">
          <h2 className="text-lg font-bold text-slate-900">Review before submit</h2>
          <p className="text-sm text-slate-600 mt-1">
            {markedQs.length === 0
              ? "You haven't marked any question for review."
              : `${markedQs.length} question${markedQs.length === 1 ? "" : "s"} marked for review.`}
            {unansweredCount > 0 && (
              <span className="block mt-1 text-amber-700">
                {unansweredCount} question{unansweredCount === 1 ? " is" : "s are"} unanswered.
              </span>
            )}
          </p>
        </div>

        {markedQs.length > 0 && (
          <div className="p-5 max-h-72 overflow-y-auto border-b border-slate-200">
            <ul className="divide-y divide-slate-100">
              {markedQs.map((q) => {
                const i = attempt.questions.findIndex((qq) => qq.id === q.id);
                const ans = attempt.user_answers[q.id];
                return (
                  <li key={q.id}>
                    <button
                      onClick={() => onJumpTo(q.id)}
                      className="w-full text-left py-2 hover:bg-slate-50 rounded px-2 -mx-2"
                    >
                      <div className="text-xs text-slate-500">
                        Question {i + 1}{ans ? ` · answered ${ans}` : " · unanswered"}
                      </div>
                      <div className="text-sm text-slate-900 line-clamp-2 mt-0.5">
                        {q.stem}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        <div className="p-5 flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50"
          >
            Go back to review
          </button>
          <button
            onClick={onConfirm}
            disabled={submitting}
            className="px-5 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50"
          >
            {submitting ? "Submitting…" : "Submit final"}
          </button>
        </div>
      </div>
    </div>
  );
}
