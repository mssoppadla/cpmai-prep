"use client";
/**
 * Lesson player at /courses/[slug]/lessons/[lid].
 *
 * Two-pane layout mirroring the LMS reference UI:
 *   - Left sidebar:  Contents = collapsible chapters, numbered lessons,
 *                    type icon, mandatory tag, completion bullet.
 *   - Main pane:     Type-specific body — video / text / quiz / checklist —
 *                    plus Prev/Next + Description/Q&A tabs +
 *                    Download Files + per-user note + (for quizzes) attempt UI.
 *
 * Progress tracking:
 *   - On lesson open: PUT progress with started_at via mark_completed=false
 *     no-op (server stamps started_at if first view).
 *   - On Mark complete click: PUT progress mark_completed=true.
 *   - Completion stamps cascade to enrollment.completed_at via the backend's
 *     ``recalculate_completion`` helper.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { lmsPublic, errMsg } from "@/lib/api";
import { SiteHeader } from "@/components/layout/SiteHeader";
import RenderBlocks from "@/components/cms/RenderBlocks";
import type {
  CourseDetailPublicOut, LessonProgressOut, QuizQuestionOut,
  QuizAttemptOut, QuizAttemptAnswerIn, LessonNoteOut,
} from "@/types/api";


type LessonInTree = CourseDetailPublicOut["chapters"][number]["lessons"][number];


function lessonTypeIcon(type: string): string {
  switch (type) {
    case "video":     return "▶";
    case "quiz":      return "✓";
    case "checklist": return "☑";
    default:          return "📄";
  }
}


export default function LessonPlayerPage({
  params,
}: { params: { slug: string; lid: string } }) {
  const router = useRouter();
  const lessonId = Number(params.lid);

  const [detail, setDetail] = useState<CourseDetailPublicOut | null>(null);
  const [progress, setProgress] = useState<Record<number, LessonProgressOut>>({});
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"description" | "discussion">("description");

  // Find current lesson + flattened list (for Prev/Next nav).
  const allLessons: LessonInTree[] = useMemo(() => {
    if (!detail) return [];
    return detail.chapters.flatMap((ch) => ch.lessons);
  }, [detail]);
  const currentIdx = allLessons.findIndex((l) => l.id === lessonId);
  const current = allLessons[currentIdx] ?? null;
  const prevLesson = currentIdx > 0 ? allLessons[currentIdx - 1] : null;
  const nextLesson = currentIdx >= 0 && currentIdx < allLessons.length - 1
                     ? allLessons[currentIdx + 1] : null;
  const myEnrollmentId = useMemo(() => {
    // Detail doesn't include enrollment id; we fetch via the helper below
    return null;
  }, []);
  const [enrollmentId, setEnrollmentId] = useState<number | null>(null);

  // ----------------------------------------------------- load detail + progress

  useEffect(() => {
    (async () => {
      try {
        const d = await lmsPublic.getCourse(params.slug);
        setDetail(d);
        if (d.is_enrolled) {
          // Get enrollment for progress queries
          const mine = await lmsPublic.myEnrollments();
          const enr = mine.find((e) => e.course_id === d.course.id) ?? null;
          if (enr) {
            setEnrollmentId(enr.id);
            const prog = await lmsPublic.listProgress(enr.id);
            const byLesson: Record<number, LessonProgressOut> = {};
            for (const p of prog) byLesson[p.lesson_id] = p;
            setProgress(byLesson);
          }
        }
      } catch (e) { setErr(errMsg(e)); }
    })();
  }, [params.slug]);

  // Mark "started" on first open (debounced)
  useEffect(() => {
    if (!enrollmentId || !current) return;
    // If we don't have progress for this lesson yet, ping the server
    // with no-op so it stamps started_at.
    if (!progress[current.id]) {
      lmsPublic.updateProgress(enrollmentId, current.id, {})
        .then((p) => setProgress((prev) => ({ ...prev, [current.id]: p })))
        .catch((e) => {
          // Don't surface to UI — this is a background started-marker
          // ping the user didn't initiate, and most failures (401 token
          // expiry mid-session, network blip) recover on the next
          // lesson open. But a CONSISTENT failure in prod means
          // completion never tracks; console.error gives ops + dev
          // tools enough to spot a broken /lms/progress endpoint.
          console.error("[lesson player] progress ping (started)", e);
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enrollmentId, current?.id]);

  async function markComplete() {
    if (!enrollmentId || !current) return;
    try {
      const p = await lmsPublic.updateProgress(enrollmentId, current.id, { mark_completed: true });
      setProgress((prev) => ({ ...prev, [current.id]: p }));
    } catch (e) { setErr(errMsg(e)); }
  }

  // ----------------------------------------------------- render guards

  if (err && !detail) {
    return (
      <>
        <SiteHeader />
        <main className="min-h-screen max-w-3xl mx-auto px-6 py-10">
          <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">{err}</div>
        </main>
      </>
    );
  }
  if (!detail || !current) {
    return (
      <>
        <SiteHeader />
        <main className="min-h-screen p-8 text-slate-500 text-sm">Loading lesson…</main>
      </>
    );
  }
  if (!current.is_free_preview && !detail.is_enrolled) {
    return (
      <>
        <SiteHeader />
        <main className="min-h-screen max-w-3xl mx-auto px-6 py-10">
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-6">
            <h2 className="font-semibold text-amber-900">Enrol to access this lesson</h2>
            <p className="text-sm text-amber-800 mt-2">
              This lesson is only available to enrolled students.
            </p>
            <Link href={`/courses/${params.slug}`}
                  className="inline-block mt-4 px-4 py-2 bg-amber-600 text-white text-sm font-medium rounded-lg hover:bg-amber-700">
              Back to course page
            </Link>
          </div>
        </main>
      </>
    );
  }

  // Calculate completion bullet for sidebar items
  const isCompleted = (lid: number) => progress[lid]?.completed_at != null;

  return (
    <>
      <SiteHeader />
      <div className="flex min-h-screen">
        {/* ============ Left sidebar: contents ============ */}
        <aside className={`${sidebarOpen ? "w-72" : "w-12"} shrink-0 bg-white border-r border-slate-200 transition-all`}>
          <div className="sticky top-0 px-4 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            {sidebarOpen && <span className="font-semibold text-slate-900 text-sm">Contents</span>}
            <button onClick={() => setSidebarOpen((o) => !o)}
                    className="p-1 rounded hover:bg-slate-200"
                    aria-label="Toggle sidebar">
              <span className="text-xs">{sidebarOpen ? "◀" : "▶"}</span>
            </button>
          </div>
          {sidebarOpen && (
            <nav className="overflow-y-auto" style={{ maxHeight: "calc(100vh - 120px)" }}>
              {detail.chapters.map((ch, ci) => (
                <div key={ch.id}>
                  <div className="px-4 py-2 bg-slate-50 border-b border-slate-200 text-sm font-medium flex items-center gap-2">
                    <span className="text-slate-500 font-mono text-xs">{ci + 1}</span>
                    <span className="text-slate-900">{ch.title}</span>
                    {ch.is_mandatory && (
                      <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase bg-indigo-100 text-indigo-700 rounded">
                        Mandatory
                      </span>
                    )}
                  </div>
                  <ul>
                    {ch.lessons.map((l, li) => {
                      const active = l.id === lessonId;
                      const completed = isCompleted(l.id);
                      const canOpen = detail.is_enrolled || l.is_free_preview;
                      return (
                        <li key={l.id}>
                          {canOpen ? (
                            <Link href={`/courses/${params.slug}/lessons/${l.id}`}
                                  className={`flex items-start gap-2 px-4 py-2 text-sm border-l-2 ${
                                    active
                                      ? "border-indigo-600 bg-indigo-50"
                                      : "border-transparent hover:bg-slate-50"
                                  }`}>
                              <span className={completed ? "text-indigo-600" : "text-slate-300"}>
                                {completed ? "●" : "○"}
                              </span>
                              <span className="text-slate-400">{lessonTypeIcon(l.lesson_type)}</span>
                              <span className="flex-1 leading-snug">
                                <span className="text-slate-500 font-mono text-xs">{ci + 1}.{li + 1}: </span>
                                <span className={active ? "font-medium text-indigo-900" : "text-slate-900"}>
                                  {l.title}
                                </span>
                                {l.is_mandatory && (
                                  <span className="ml-1 px-1 py-0.5 text-[9px] font-bold uppercase bg-indigo-100 text-indigo-700 rounded">
                                    Mandatory
                                  </span>
                                )}
                              </span>
                            </Link>
                          ) : (
                            <div className="flex items-start gap-2 px-4 py-2 text-sm text-slate-400">
                              <span>🔒</span>
                              <span>{ci + 1}.{li + 1}: {l.title}</span>
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            </nav>
          )}
        </aside>

        {/* ============ Main pane ============ */}
        <main className="flex-1 min-w-0">
          {/* Top bar: title + Prev/Next */}
          <header className="sticky top-0 z-10 bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between">
            <div className="text-sm">
              <Link href={`/courses/${params.slug}`}
                    className="text-xs text-slate-500 hover:underline">
                ← {detail.course.title}
              </Link>
              <h1 className="font-semibold text-slate-900 mt-0.5">{current.title}</h1>
            </div>
            <div className="flex gap-2">
              <button onClick={() => prevLesson && router.push(`/courses/${params.slug}/lessons/${prevLesson.id}`)}
                      disabled={!prevLesson}
                      className="px-3 py-1.5 bg-white border border-slate-300 text-slate-700 text-xs font-medium rounded hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed">
                ← Prev
              </button>
              <button onClick={() => nextLesson && router.push(`/courses/${params.slug}/lessons/${nextLesson.id}`)}
                      disabled={!nextLesson}
                      className="px-3 py-1.5 bg-indigo-600 text-white text-xs font-medium rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed">
                Next →
              </button>
            </div>
          </header>

          {err && (
            <div role="alert" className="mx-6 mt-4 bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg text-sm">{err}</div>
          )}

          {/* Tabs (Description / Q&A) — only when discussion_url exists */}
          {current.discussion_url && (
            <div className="border-b border-slate-200 px-6">
              <div className="flex gap-4 text-sm">
                <button onClick={() => setTab("description")}
                        className={`py-3 border-b-2 ${
                          tab === "description"
                            ? "border-indigo-600 text-indigo-700 font-medium"
                            : "border-transparent text-slate-500 hover:text-slate-900"
                        }`}>
                  📝 Description
                </button>
                <a href={current.discussion_url} target="_blank" rel="noopener noreferrer"
                   className="py-3 border-b-2 border-transparent text-slate-500 hover:text-slate-900">
                  💬 Ask Questions (on Discord)
                </a>
              </div>
            </div>
          )}

          {/* Body */}
          <div className="px-6 py-6 max-w-4xl mx-auto">
            <LessonBody lesson={current} progress={progress[current.id] ?? null}
                        enrollmentId={enrollmentId}
                        onMarkComplete={markComplete}
                        onProgressUpdate={(p) => setProgress((prev) => ({ ...prev, [current.id]: p }))}
                        slug={params.slug} />

            {/* Files */}
            {"files" in current && (current as LessonInTree & { files?: unknown[] }).files
              && ((current as LessonInTree & { files: { id: number; filename: string; file_url: string; file_category: string }[] }).files.length > 0) && (
              <section className="mt-8 bg-yellow-50 border border-yellow-200 rounded-xl p-4">
                <h3 className="font-semibold text-yellow-900 mb-2 flex items-center gap-2">
                  📁 Download Files
                </h3>
                <ul className="space-y-1">
                  {(current as LessonInTree & { files: { id: number; filename: string; file_url: string; file_category: string }[] }).files.map((f) => (
                    <li key={f.id} className="text-sm">
                      <a href={f.file_url} target="_blank" rel="noopener noreferrer"
                         className="text-indigo-700 hover:underline">
                        {f.filename}
                      </a>
                      <span className="ml-2 text-xs text-slate-600">[{f.file_category}]</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Notes (enrolled only) */}
            {detail.is_enrolled && enrollmentId !== null && (
              <NoteEditor lessonId={current.id} />
            )}

            {/* Mark complete button */}
            {detail.is_enrolled && current.lesson_type !== "quiz" && (
              <div className="mt-8 flex justify-end">
                {progress[current.id]?.completed_at ? (
                  <button onClick={markComplete}
                          className="px-4 py-2 bg-emerald-100 text-emerald-800 text-sm font-medium rounded-lg">
                    ✓ Completed
                  </button>
                ) : (
                  <button onClick={markComplete}
                          className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
                    Mark complete
                  </button>
                )}
              </div>
            )}
          </div>
        </main>
      </div>
    </>
  );
}


// ====================================================== Lesson body (type-specific)

function LessonBody({
  lesson, progress, enrollmentId, onMarkComplete, onProgressUpdate, slug,
}: {
  lesson: LessonInTree;
  progress: LessonProgressOut | null;
  enrollmentId: number | null;
  onMarkComplete: () => void;
  onProgressUpdate: (p: LessonProgressOut) => void;
  slug: string;
}) {
  void slug;
  if (lesson.lesson_type === "video") {
    return <VideoLesson lesson={lesson} progress={progress}
                        enrollmentId={enrollmentId}
                        onProgressUpdate={onProgressUpdate}
                        onComplete={onMarkComplete} />;
  }
  if (lesson.lesson_type === "quiz") {
    return <QuizLesson lessonId={lesson.id} />;
  }
  if (lesson.lesson_type === "checklist") {
    return <ChecklistLesson lesson={lesson} progress={progress}
                            enrollmentId={enrollmentId}
                            onProgressUpdate={onProgressUpdate} />;
  }
  // text / default
  return (
    <article className="prose-cms">
      <RenderBlocks blocks={lesson.body_blocks ?? []} />
      {(!lesson.body_blocks || lesson.body_blocks.length === 0) && (
        <p className="text-slate-500 text-sm italic">
          This lesson doesn&apos;t have content yet.
        </p>
      )}
    </article>
  );
}


// ====================================================== Video lesson

function VideoLesson({
  lesson, progress, enrollmentId, onProgressUpdate, onComplete,
}: {
  lesson: LessonInTree;
  progress: LessonProgressOut | null;
  enrollmentId: number | null;
  onProgressUpdate: (p: LessonProgressOut) => void;
  onComplete: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  // Last saved position — comes from the server on load, so resume works
  // across refreshes AND across devices (it's not a local-only cache).
  const resumeAt = progress?.last_position_seconds ?? 0;

  // Persist the current position to the server. The 10s throttle on
  // timeupdate keeps the row roughly fresh during playback; this is the
  // "save now" used on pause / tab-hide / unmount so that pausing and
  // then refreshing (or closing) resumes from the right spot — the old
  // code only wrote on the 10s boundary, so a pause at 0:07 was lost.
  const savePosition = useCallback((seconds: number) => {
    if (!enrollmentId || !Number.isFinite(seconds) || seconds <= 0) return;
    lmsPublic.updateProgress(enrollmentId, lesson.id, {
      last_position_seconds: Math.floor(seconds),
    }).then(onProgressUpdate).catch((err) => {
      // Background write — failing silently would hide a broken
      // /lms/progress endpoint (the learner thinks resume is saved but
      // it isn't). console.error gives devtools + log collectors a hook
      // without nagging mid-video.
      console.error("[lesson player] progress save", err);
    });
  }, [enrollmentId, lesson.id, onProgressUpdate]);

  // Flush position when the tab is hidden or the component unmounts
  // (route change / navigation) so a quick pause-then-leave is captured.
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden" && videoRef.current) {
        savePosition(videoRef.current.currentTime);
      }
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      if (videoRef.current) savePosition(videoRef.current.currentTime);
    };
  }, [savePosition]);

  if (!lesson.video_url) {
    return <p className="text-slate-500 text-sm italic">Video URL not configured.</p>;
  }
  // YouTube embed for youtube.com / youtu.be URLs; HTML5 <video> otherwise.
  const isYouTube = /youtube\.com|youtu\.be/.test(lesson.video_url);
  if (isYouTube) {
    const id = extractYouTubeId(lesson.video_url);
    if (!id) {
      return <p className="text-rose-600 text-sm">Could not parse YouTube URL.</p>;
    }
    return (
      <div className="aspect-video w-full rounded-lg overflow-hidden bg-black">
        <iframe
          src={`https://www.youtube-nocookie.com/embed/${id}?rel=0`}
          className="w-full h-full"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          title={lesson.title}
        />
      </div>
    );
  }
  return (
    <video
      ref={videoRef}
      src={lesson.video_url}
      controls
      className="w-full rounded-lg bg-black"
      preload="metadata"
      onLoadedMetadata={(e) => {
        // Resume from the last saved position. Guard against seeking at
        // or past the end (a fully-watched video should replay from 0).
        const v = e.currentTarget;
        if (resumeAt > 0 && Number.isFinite(v.duration) && resumeAt < v.duration - 2) {
          v.currentTime = resumeAt;
        }
      }}
      onTimeUpdate={(e) => {
        // Throttle progress writes: only every 10 seconds of playback.
        const v = e.currentTarget;
        if (Math.floor(v.currentTime) % 10 !== 0) return;
        savePosition(v.currentTime);
      }}
      onPause={(e) => savePosition(e.currentTarget.currentTime)}
      onEnded={() => {
        // Auto-mark the lesson complete when the video finishes.
        onComplete();
      }}
    />
  );
}

function extractYouTubeId(url: string): string | null {
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtu.be")) {
      return u.pathname.slice(1).split("/")[0] || null;
    }
    return u.searchParams.get("v");
  } catch { return null; }
}


// ====================================================== Quiz lesson

type QuestionWithOptions = QuizQuestionOut & {
  options: Array<{ id: number; position: number; text: string }>;
};

function QuizLesson({ lessonId }: { lessonId: number }) {
  const [questions, setQuestions] = useState<QuestionWithOptions[] | null>(null);
  const [answers, setAnswers] = useState<Record<number, QuizAttemptAnswerIn>>({});
  const [result, setResult] = useState<QuizAttemptOut | null>(null);
  const [attempts, setAttempts] = useState<QuizAttemptOut[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        // Public endpoint now returns options nested inline.
        const qs = await lmsPublic.listQuizQuestions(lessonId) as unknown as QuestionWithOptions[];
        setQuestions(qs);
        setAttempts(await lmsPublic.listMyAttempts(lessonId));
      } catch (e) { setErr(errMsg(e)); }
    })();
  }, [lessonId]);

  function toggleOption(q: QuestionWithOptions, optionId: number) {
    setAnswers((prev) => {
      const cur = prev[q.id]?.selected_option_ids ?? [];
      const single = q.question_type === "single_choice" || q.question_type === "true_false";
      const next = single
        ? [optionId]
        : cur.includes(optionId)
          ? cur.filter((x) => x !== optionId)
          : [...cur, optionId];
      return { ...prev, [q.id]: { question_id: q.id, selected_option_ids: next } };
    });
  }

  async function submit() {
    setErr(null);
    try {
      const r = await lmsPublic.submitQuizAttempt(lessonId, {
        answers: (questions ?? []).map((q) => answers[q.id] ?? { question_id: q.id }),
      });
      setResult(r);
      setAttempts(await lmsPublic.listMyAttempts(lessonId));
    } catch (e) { setErr(errMsg(e)); }
  }

  function reset() {
    setResult(null);
    setAnswers({});
  }

  if (err) return <div className="text-rose-700 text-sm">{err}</div>;
  if (!questions) return <div className="text-slate-500 text-sm">Loading quiz…</div>;

  if (result) {
    return (
      <div className="space-y-4">
        <div className={`rounded-lg p-6 ${result.passed
            ? "bg-emerald-50 border border-emerald-200"
            : "bg-rose-50 border border-rose-200"}`}>
          <div className="text-xl font-bold">
            {result.passed ? "✓ Passed" : "✗ Did not pass"}
          </div>
          <div className="text-sm mt-2">
            Score: {result.score_points} / {result.max_points} ({result.percent}%)
          </div>
          <button onClick={reset}
                  className="mt-4 px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50">
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold text-slate-900">Quiz</h2>
      {attempts.length > 0 && (
        <p className="text-xs text-slate-600">
          Past attempts: {attempts.length} · best score{" "}
          {Math.max(...attempts.map((a) => a.percent))}%
        </p>
      )}
      {questions.map((q, i) => {
        const sel = answers[q.id]?.selected_option_ids ?? [];
        return (
          <div key={q.id} className="bg-white border border-slate-200 rounded-lg p-4">
            <div className="font-medium text-slate-900 mb-2">
              Q{i + 1}. {q.question_text}
            </div>
            {q.question_type === "short_answer" ? (
              <input
                value={answers[q.id]?.short_answer_text ?? ""}
                onChange={(e) => setAnswers((prev) => ({
                  ...prev,
                  [q.id]: { question_id: q.id, short_answer_text: e.target.value },
                }))}
                placeholder="Your answer"
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
              />
            ) : (
              <div className="space-y-2 mt-2">
                {(q.options ?? []).map((o) => {
                  const checked = sel.includes(o.id);
                  const isSingle = q.question_type === "single_choice"
                                || q.question_type === "true_false";
                  return (
                    <label key={o.id}
                           className={`flex items-center gap-2 px-3 py-2 border rounded-lg cursor-pointer ${
                             checked
                               ? "border-indigo-500 bg-indigo-50"
                               : "border-slate-300 hover:bg-slate-50"
                           }`}>
                      <input type={isSingle ? "radio" : "checkbox"}
                             name={`q-${q.id}`}
                             checked={checked}
                             onChange={() => toggleOption(q, o.id)} />
                      <span className="text-sm">{o.text}</span>
                    </label>
                  );
                })}
                {(q.options ?? []).length === 0 && (
                  <p className="text-xs text-slate-500 italic">
                    No options configured for this question yet.
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}
      <button onClick={submit}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700">
        Submit
      </button>
    </div>
  );
}


// ====================================================== Checklist lesson

function ChecklistLesson({
  lesson, progress, enrollmentId, onProgressUpdate,
}: {
  lesson: LessonInTree & { checklist_items?: Array<{ text: string }> };
  progress: LessonProgressOut | null;
  enrollmentId: number | null;
  onProgressUpdate: (p: LessonProgressOut) => void;
}) {
  const items = (lesson as unknown as { checklist_items?: Array<{ text: string }> }).checklist_items ?? [];
  const state = (progress?.checklist_state as Record<string, boolean> | undefined) ?? {};

  async function toggle(idx: number) {
    if (!enrollmentId) return;
    const next = { ...state, [String(idx)]: !state[String(idx)] };
    try {
      const p = await lmsPublic.updateProgress(enrollmentId, lesson.id, {
        checklist_state: next,
      });
      onProgressUpdate(p);
    } catch {}
  }

  if (items.length === 0) {
    return <p className="text-slate-500 text-sm italic">No checklist items.</p>;
  }
  return (
    <div className="space-y-2">
      <h2 className="text-xl font-bold text-slate-900 mb-3">Checklist</h2>
      {items.map((it, i) => {
        const checked = !!state[String(i)];
        return (
          <label key={i} className="flex gap-3 items-start cursor-pointer bg-white border border-slate-200 rounded-lg p-3 hover:bg-slate-50">
            <input type="checkbox" checked={checked}
                   onChange={() => toggle(i)} className="mt-1" />
            <span className={`text-sm ${checked ? "text-slate-400 line-through" : "text-slate-800"}`}>
              {it.text}
            </span>
          </label>
        );
      })}
    </div>
  );
}


// ====================================================== Note editor

function NoteEditor({ lessonId }: { lessonId: number }) {
  const [note, setNote] = useState<LessonNoteOut | null>(null);
  const [body, setBody] = useState("");
  const [saved, setSaved] = useState<"idle" | "saving" | "saved">("idle");

  useEffect(() => {
    lmsPublic.getMyNote(lessonId).then((n) => {
      setNote(n);
      setBody(n?.body ?? "");
    }).catch((e) => {
      // Note GET fails → the editor starts blank (note=null, body="").
      // If the user types and saves, the save path creates a fresh
      // row, which is correct UX but loses any pre-existing server
      // note silently. console.error so a broken /lms/notes GET in
      // prod surfaces in devtools instead of vanishing the user's
      // previous notes without a trace.
      console.error("[lesson player] note load failed", e);
    });
  }, [lessonId]);

  useEffect(() => {
    if (body === (note?.body ?? "")) return;
    setSaved("saving");
    const t = setTimeout(async () => {
      try {
        const n = await lmsPublic.upsertMyNote(lessonId, body);
        setNote(n);
        setSaved("saved");
      } catch {}
    }, 1500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body]);

  return (
    <section className="mt-8 bg-white border border-slate-200 rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold text-slate-900 text-sm">📓 My notes</h3>
        <span className="text-xs text-slate-500">
          {saved === "saving" && "Saving…"}
          {saved === "saved" && "Saved"}
        </span>
      </div>
      <textarea value={body} rows={3}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Take notes on this lesson…"
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
    </section>
  );
}
