"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ApiError, auth, exams as examsApi, errMsg } from "@/lib/api";
import type { ExamAttemptOut, UserOut } from "@/types/api";
import {
  QuestionCard, type QuestionRanges, type Tool,
} from "@/components/exam/QuestionCard";

/** Per-question annotation ranges keyed by question ID. */
type AnnotationsByQ = Record<number, QuestionRanges>;

const annKey  = (attemptId: number) => `cpmai.exam.annotations.${attemptId}`;
const markKey = (attemptId: number) => `cpmai.exam.marked.${attemptId}`;

/** Convert any thrown error into a discriminated-friendly shape. */
function toApiErr(e: unknown): { message: string; code: string; status: number } {
  if (e instanceof ApiError) {
    return {
      message: e.body?.message ?? `HTTP ${e.status}`,
      code: e.body?.code ?? "unknown_error",
      status: e.status,
    };
  }
  return { message: errMsg(e), code: "unknown_error", status: 0 };
}

export default function ExamAttemptPage() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();
  const [attempt, setAttempt] = useState<ExamAttemptOut | null>(null);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<{ message: string; code: string; status: number } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [marked, setMarked] = useState<Record<number, boolean>>({});
  const [annotations, setAnnotations] = useState<AnnotationsByQ>({});
  const [tool, setTool] = useState<Tool>("none");
  const [reviewMode, setReviewMode] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [me, setMe] = useState<UserOut | null | undefined>(undefined);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Resolve auth state in parallel with starting the attempt — used to
  // surface an "anonymous: result won't be saved" banner for guest users.
  useEffect(() => {
    auth.me().then(setMe).catch(() => setMe(null));
  }, []);

  // Start the attempt on mount, restore local annotations / marked.
  // `?domain=D-I` switches this into a focused domain-practice drill over
  // just that domain's questions in the set (reached from the results
  // screen). No query param → a normal full-set sitting.
  useEffect(() => {
    const domain = typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("domain")
      : null;
    const starting = domain
      ? examsApi.startDomainPractice(slug, domain)
      : examsApi.startAttempt(slug);
    starting
      .then((a) => {
        setAttempt(a);
        const secs = Math.max(0,
          Math.floor((new Date(a.expires_at).getTime() - Date.now()) / 1000));
        setSecondsLeft(secs);
        try {
          const ann = JSON.parse(localStorage.getItem(annKey(a.id)) ?? "{}");
          setAnnotations(ann);
          const mk = JSON.parse(localStorage.getItem(markKey(a.id)) ?? "{}");
          setMarked(mk);
        } catch { /* ignore */ }
      })
      .catch((e) => {
        console.error("[exam] start", e);
        setError(toApiErr(e));
      });
    return () => { if (tickRef.current) clearInterval(tickRef.current); };
  }, [slug]);

  useEffect(() => {
    if (!attempt) return;
    localStorage.setItem(annKey(attempt.id), JSON.stringify(annotations));
  }, [annotations, attempt]);
  useEffect(() => {
    if (!attempt) return;
    localStorage.setItem(markKey(attempt.id), JSON.stringify(marked));
  }, [marked, attempt]);

  // Reset the active tool on every question navigation. The user must
  // intentionally re-select highlight/strike/eraser for each question.
  useEffect(() => {
    setTool("none");
  }, [index]);

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

  const reviewIds = useMemo(() =>
    Object.entries(marked).filter(([, v]) => v).map(([k]) => Number(k)),
    [marked]);
  const unansweredCount = useMemo(() => {
    if (!attempt) return 0;
    return attempt.questions.filter(
      (qq) => attempt.user_answers[qq.id] == null,
    ).length;
  }, [attempt]);

  // Wire-shape ↔ array helpers. `user_answers[qid]` is either a single
  // letter ("B"), a comma-joined sorted multi list ("A,C"), or null.
  // The QuestionCard always works in array shape.
  function wireToArr(v: string | null | undefined): string[] {
    if (!v) return [];
    return v.split(",").filter(Boolean);
  }
  function arrToWire(letters: string[]): string | null {
    return letters.length === 0 ? null
      : [...letters].sort().join(",");
  }

  const handleSelect = useCallback(async (letters: string[]) => {
    if (!attempt) return;
    const q = attempt.questions[index];
    const wire = arrToWire(letters);
    const next = { ...attempt, user_answers: { ...attempt.user_answers, [q.id]: wire } };
    setAttempt(next);
    try {
      // Send the right field for the question's type — server enforces
      // the shape (mismatch returns 409).
      const payload =
        q.question_type === "multi_choice"
          ? { question_id: q.id, selected_letters: letters,
              marked_for_review: marked[q.id] ?? false }
          : { question_id: q.id, selected_letter: letters[0] ?? null,
              marked_for_review: marked[q.id] ?? false };
      await examsApi.saveAnswer(attempt.id, payload);
    } catch (e) {
      console.error("[exam] saveAnswer", e);
      setError(toApiErr(e));
    }
  }, [attempt, index, marked]);

  const toggleReview = useCallback(async () => {
    if (!attempt) return;
    const q = attempt.questions[index];
    const next = { ...marked, [q.id]: !(marked[q.id] ?? false) };
    setMarked(next);
    try {
      const arr = wireToArr(attempt.user_answers[q.id]);
      const payload =
        q.question_type === "multi_choice"
          ? { question_id: q.id, selected_letters: arr,
              marked_for_review: next[q.id] }
          : { question_id: q.id, selected_letter: arr[0] ?? null,
              marked_for_review: next[q.id] };
      await examsApi.saveAnswer(attempt.id, payload);
    } catch (e) {
      console.error("[exam] saveAnswer mark", e);
      setError(toApiErr(e));
    }
  }, [attempt, index, marked]);

  const handleRangesChange = useCallback((q_id: number, next: QuestionRanges) => {
    setAnnotations((all) => ({ ...all, [q_id]: next }));
  }, []);

  async function confirmSubmit() {
    if (!attempt || submitting) return;
    setSubmitting(true);
    try {
      const result = await examsApi.submit(attempt.id);
      try {
        localStorage.removeItem(annKey(attempt.id));
        localStorage.removeItem(markKey(attempt.id));
      } catch { /* ignore */ }
      router.push(`/exams/results/${result.id}`);
    } catch (e) {
      console.error("[exam] submit", e);
      setError(toApiErr(e));
      setSubmitting(false);
    }
  }

  if (error) {
    const here = encodeURIComponent(`/exams/${slug}`);
    const isAuth = error.code === "unauthorized" || error.status === 401;
    const isPaywall = error.code === "subscription_required" || error.status === 402;
    return (
      <main className="max-w-2xl mx-auto px-6 py-10">
        <div className="flex items-center justify-between text-xs text-slate-500 mb-4">
          <Link href="/exams" className="hover:text-indigo-600">← All exam sets</Link>
          <Link href="/" className="hover:text-indigo-600">Home / FAQs</Link>
        </div>

        {isAuth ? (
          <div className="bg-white rounded-xl border border-slate-200 p-6">
            <h1 className="text-xl font-bold text-slate-900 mb-2">
              Sign in to start this premium set
            </h1>
            <p className="text-sm text-slate-600 mb-5">
              This set requires a signed-in account with an active
              subscription. Free sets are available without signing in
              (results won't be saved unless you log in).
            </p>
            <div className="flex flex-col sm:flex-row gap-2">
              <Link
                href={`/login?next=${here}`}
                className="px-5 py-2.5 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700 text-center"
              >
                Sign in (Google or password)
              </Link>
              <Link
                href="/exams"
                className="px-5 py-2.5 bg-white text-slate-700 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50 text-center"
              >
                Browse other sets
              </Link>
            </div>
          </div>
        ) : isPaywall ? (
          <div className="bg-gradient-to-br from-indigo-50 to-purple-50 rounded-xl border border-indigo-200 p-6">
            <h1 className="text-xl font-bold text-slate-900 mb-2">
              This is a premium exam set
            </h1>
            <p className="text-sm text-indigo-900 mb-5">
              Subscribe to unlock advanced sets, the AI tutor with extended
              quota, and full performance analytics. Cancel anytime.
            </p>
            <div className="flex flex-col sm:flex-row gap-2">
              <Link
                href="/pricing"
                className="px-5 py-2.5 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700 text-center"
              >
                View plans &amp; subscribe
              </Link>
              <Link
                href={`/login?next=${here}`}
                className="px-5 py-2.5 bg-white text-slate-700 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50 text-center"
              >
                Sign in with another account
              </Link>
              <Link
                href="/exams"
                className="px-5 py-2.5 bg-white text-slate-700 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50 text-center"
              >
                Pick a free set
              </Link>
            </div>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-slate-200 p-6">
            <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg mb-5 text-sm">
              {error.message}
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <Link
                href="/exams"
                className="px-5 py-2.5 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700 text-center"
              >
                Back to exam sets
              </Link>
              <Link
                href="/"
                className="px-5 py-2.5 bg-white text-slate-700 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50 text-center"
              >
                Home
              </Link>
            </div>
          </div>
        )}
      </main>
    );
  }
  if (!attempt) {
    return <main className="max-w-2xl mx-auto px-6 py-10 text-slate-500">Starting attempt...</main>;
  }

  // Review-mode screen replaces the question UI entirely.
  if (reviewMode) {
    return (
      <ReviewScreen
        attempt={attempt}
        markedIds={reviewIds}
        unansweredCount={unansweredCount}
        submitting={submitting}
        onJumpTo={(qid) => {
          const i = attempt.questions.findIndex((qq) => qq.id === qid);
          if (i >= 0) setIndex(i);
          setReviewMode(false);
        }}
        onEnd={() => setReviewMode(false)}
        onSubmit={confirmSubmit}
      />
    );
  }

  const q = attempt.questions[index];
  const selected = wireToArr(attempt.user_answers[q.id]);
  const markedForReview = marked[q.id] ?? false;
  const qRanges = annotations[q.id] ?? {};

  const mm = String(Math.floor(secondsLeft / 60)).padStart(2, "0");
  const ss = String(secondsLeft % 60).padStart(2, "0");
  const lowTime = secondsLeft < 300;

  return (
    <main className="max-w-3xl mx-auto px-6 py-8">
      {/* Top utility row — quick exit back to home/FAQs or learner dashboard. */}
      <div className="flex items-center justify-between text-xs text-slate-500 mb-4">
        <Link href="/dashboard" className="hover:text-indigo-600">
          ← Dashboard
        </Link>
        <Link href="/#faq-heading" className="hover:text-indigo-600">
          Home / FAQs
        </Link>
      </div>

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

      {me === null && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4 text-sm text-amber-900 flex flex-col sm:flex-row sm:items-center gap-2">
          <div className="flex-1">
            <strong>You're attempting anonymously.</strong>{" "}
            Your result will be visible after submit but won't be saved to a
            dashboard. Sign in to save attempts and track progress.
          </div>
          <Link
            href={`/login?next=${encodeURIComponent(`/exams/${slug}`)}`}
            className="px-3 py-1.5 bg-indigo-600 text-white text-xs font-semibold rounded hover:bg-indigo-700 self-start sm:self-auto whitespace-nowrap"
          >
            Sign in
          </Link>
        </div>
      )}

      <QuestionCard
        question={q} index={index} total={attempt.questions.length}
        selected={selected} markedForReview={markedForReview}
        tool={tool} ranges={qRanges}
        onSelect={handleSelect}
        onToggleReview={toggleReview}
        onRangesChange={(next) => handleRangesChange(q.id, next)}
      />

      <div className="flex items-center justify-between mt-6 gap-3 flex-wrap">
        <button onClick={() => setIndex(Math.max(0, index - 1))}
                disabled={index === 0}
                className="px-4 py-2 text-sm font-medium text-slate-700 bg-white
                           border border-slate-300 rounded-lg disabled:opacity-50">
          ← Previous
        </button>
        <button onClick={() => setReviewMode(true)}
                className="px-4 py-2 text-sm font-medium text-amber-700 bg-amber-50
                           border border-amber-200 rounded-lg hover:bg-amber-100">
          Review marked ({reviewIds.length})
        </button>
        {index < attempt.questions.length - 1 ? (
          <button onClick={() => setIndex(index + 1)}
                  className="px-5 py-2 text-sm font-medium text-white bg-indigo-600
                             rounded-lg hover:bg-indigo-700">
            Next →
          </button>
        ) : (
          <button onClick={() => setReviewMode(true)}
                  className="px-5 py-2 text-sm font-medium text-white bg-emerald-600
                             rounded-lg hover:bg-emerald-700">
            Review &amp; submit
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
    </main>
  );
}

// ---------------------------------------------------------------------------
// Toolbox
// ---------------------------------------------------------------------------
function Toolbox({ tool, setTool }: { tool: Tool; setTool: (t: Tool) => void }) {
  const toggle = (t: Exclude<Tool, "none">) => setTool(tool === t ? "none" : t);
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
              title="Drag to highlight selected text in stem or options"
              className={cls("highlight")}><span aria-hidden>🖍</span><span className="sr-only">Highlight</span></button>
      <button type="button" onClick={() => toggle("strike")}
              title="Drag to strike through selected text"
              className={cls("strike")}><span aria-hidden>S̶</span><span className="sr-only">Strike</span></button>
      <button type="button" onClick={() => toggle("eraser")}
              title="Drag over annotated text to clear it"
              className={cls("eraser")}><span aria-hidden>🧽</span><span className="sr-only">Eraser</span></button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Review screen — full page (not modal). Lists every marked question with
// jump-back + an "End review" / "Submit final" pair.
// ---------------------------------------------------------------------------
interface ReviewScreenProps {
  attempt: ExamAttemptOut;
  markedIds: number[];
  unansweredCount: number;
  submitting: boolean;
  onJumpTo: (questionId: number) => void;
  onEnd: () => void;
  onSubmit: () => void;
}
function ReviewScreen({
  attempt, markedIds, unansweredCount, submitting,
  onJumpTo, onEnd, onSubmit,
}: ReviewScreenProps) {
  const markedQs = attempt.questions
    .map((q, idx) => ({ q, idx }))
    .filter((x) => markedIds.includes(x.q.id));

  return (
    <main className="max-w-3xl mx-auto px-6 py-8">
      <div className="mb-6">
        <button onClick={onEnd}
                className="text-sm text-slate-500 hover:text-indigo-600">
          ← End review (back to attempt)
        </button>
      </div>
      <header className="mb-5">
        <h1 className="text-2xl font-bold text-slate-900">Review marked questions</h1>
        <p className="text-sm text-slate-600 mt-1">
          {markedQs.length === 0
            ? "You haven't marked any question for review."
            : `${markedQs.length} question${markedQs.length === 1 ? "" : "s"} marked.`}
          {unansweredCount > 0 && (
            <span className="block mt-1 text-amber-700">
              {unansweredCount} of {attempt.questions.length} question{unansweredCount === 1 ? " is" : "s are"} still unanswered.
            </span>
          )}
        </p>
      </header>

      {markedQs.length > 0 ? (
        <ol className="space-y-2 mb-8">
          {markedQs.map(({ q, idx }) => {
            const ans = attempt.user_answers[q.id];
            return (
              <li key={q.id}>
                <button
                  onClick={() => onJumpTo(q.id)}
                  className="w-full text-left p-4 bg-white rounded-xl border border-slate-200 hover:border-indigo-300 hover:shadow-sm transition"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-semibold text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded">
                      Q{idx + 1}
                    </span>
                    {ans
                      ? <span className="text-xs text-emerald-700">answered: {ans}</span>
                      : <span className="text-xs text-slate-400">unanswered</span>}
                    {q.domain && (
                      <span className="text-xs text-slate-500 ml-auto">{q.domain}</span>
                    )}
                  </div>
                  <div className="text-sm text-slate-900 leading-snug line-clamp-3">{q.stem}</div>
                </button>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-500 mb-8">
          Nothing marked. Use the "Mark for review" checkbox on any question.
        </div>
      )}

      <div className="bg-white rounded-xl border border-slate-200 p-5 flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-3">
        <button onClick={onEnd}
                className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50">
          End review
        </button>
        <button onClick={onSubmit}
                disabled={submitting}
                className="px-5 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50">
          {submitting ? "Submitting…" : "Submit attempt"}
        </button>
      </div>
    </main>
  );
}
