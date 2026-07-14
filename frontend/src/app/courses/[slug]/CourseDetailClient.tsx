"use client";
/**
 * Public course detail at /courses/[slug].
 *
 * Shows course metadata + curriculum tree (chapters + lessons). Free
 * preview lessons + (if enrolled) all lessons are clickable through to
 * the lesson player. CTA changes based on enrollment state +
 * enrollment_type (Free → Enrol button; Paid → Buy now button).
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { GraduationCap } from "lucide-react";
import { lmsPublic, auth, errMsg } from "@/lib/api";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import type {
  CourseDetailPublicOut, CourseReviewOut, CourseAnnouncementOut,
} from "@/types/api";


/**
 * Interactive layer for /courses/[slug]. The SERVER page fetches the
 * course anonymously and passes it as initialDetail so the hero +
 * curriculum ship in the crawlable initial HTML. On mount this
 * component refetches once to enrich with the viewer's enrollment
 * state (is_enrolled, progress, reviews) — the content simply updates
 * in place instead of starting from a skeleton.
 */
export function CourseDetailClient({
  params, initialDetail,
}: { params: { slug: string }; initialDetail: CourseDetailPublicOut | null }) {
  const router = useRouter();
  const [detail, setDetail] = useState<CourseDetailPublicOut | null>(initialDetail);
  const [me, setMe] = useState<{ id: number } | null | undefined>(undefined);
  const [reviews, setReviews] = useState<CourseReviewOut[]>([]);
  const [announcements, setAnnouncements] = useState<CourseAnnouncementOut[]>([]);
  const [progress, setProgress] = useState<
    { percent: number; completed: number; total: number } | null
  >(null);
  const [err, setErr] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const d = await lmsPublic.getCourse(params.slug);
      setDetail(d);
      setReviews(await lmsPublic.listReviews(params.slug));
      if (d.is_enrolled) {
        setAnnouncements(await lmsPublic.listAnnouncements(params.slug));
        // Pull this course's progress from the enrollment list (computed
        // server-side) so the enrolled CTA can show "X% complete".
        try {
          const mine = await lmsPublic.myEnrollments();
          const enr = mine.find((e) => e.course_id === d.course.id);
          if (enr) {
            setProgress({
              percent: enr.progress_percent ?? 0,
              completed: enr.lessons_completed ?? 0,
              total: enr.lessons_total ?? 0,
            });
          }
        } catch { /* progress is best-effort; CTA still renders */ }
      }
    } catch (e) { setErr(errMsg(e)); }
  }, [params.slug]);

  useEffect(() => { void reload(); }, [reload]);

  useEffect(() => {
    auth.me().then((u) => setMe(u)).catch(() => setMe(null));
  }, []);

  async function selfEnroll() {
    try {
      await lmsPublic.selfEnrollFree(params.slug);
      await reload();
    } catch (e) { setErr(errMsg(e)); }
  }

  if (err && !detail) {
    return (
      <>
        <SiteHeader />
        <main className="min-h-screen max-w-3xl mx-auto px-6 py-10">
          <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">{err}</div>
          <Link href="/courses" className="inline-block mt-4 text-indigo-600 hover:underline text-sm">
            ← Back to catalog
          </Link>
        </main>
        <SiteFooter />
      </>
    );
  }
  if (!detail) {
    return (
      <>
        <SiteHeader />
        <main className="min-h-screen max-w-3xl mx-auto px-6 py-10 text-slate-500 text-sm">
          Loading course…
        </main>
        <SiteFooter />
      </>
    );
  }

  const c = detail.course;
  const totalLessons = detail.chapters.reduce((n, ch) => n + ch.lessons.length, 0);
  const firstLessonId = detail.chapters[0]?.lessons[0]?.id;

  return (
    <>
      <SiteHeader />
      <main className="min-h-screen max-w-6xl mx-auto px-6 py-8">
        {/* Hero */}
        <header className="mb-8 grid lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <Link href="/courses" className="text-xs text-slate-500 hover:underline">
              ← Courses
            </Link>
            <h1 className="text-4xl font-bold text-slate-900 mt-2">{c.title}</h1>
            {c.subtitle && <p className="text-lg text-slate-700 mt-2">{c.subtitle}</p>}
            <div className="flex items-center gap-3 mt-4 text-sm">
              <span className="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 text-xs font-medium">
                {c.difficulty}
              </span>
              <span className="text-slate-600">
                {detail.chapters.length} chapters · {totalLessons} lessons
              </span>
              {c.estimated_hours && <span className="text-slate-600">· {c.estimated_hours}h</span>}
            </div>
            {c.description && (
              <p className="text-slate-700 mt-4 leading-relaxed">{c.description}</p>
            )}
            {c.learning_outcomes.length > 0 && (
              <section className="mt-6">
                <h2 className="font-semibold text-slate-900 mb-2">What you&apos;ll learn</h2>
                <ul className="space-y-1">
                  {c.learning_outcomes.map((o, i) => (
                    <li key={i} className="flex gap-2 text-sm text-slate-700">
                      <span className="text-emerald-600">✓</span>
                      <span>{o}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>

          {/* CTA card */}
          <aside className="bg-white border border-slate-200 rounded-xl p-5 h-fit shadow-sm lg:sticky lg:top-6">
            {c.cover_image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={c.cover_image_url} alt="" className="aspect-video w-full object-cover rounded-lg mb-4" />
            ) : (
              <div className="aspect-video w-full rounded-lg mb-4 bg-gradient-to-br from-indigo-100 to-purple-100 grid place-items-center text-indigo-300">
                <GraduationCap size={44} />
              </div>
            )}
            {detail.is_enrolled ? (
              // Enrolled: surface progress, not price. The bar sits directly
              // above the resume CTA so the next action is obvious.
              <>
                {(() => {
                  const pct = progress?.percent ?? 0;
                  const done = pct >= 100;
                  return (
                    <div className="mb-4">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-sm font-semibold text-slate-900">
                          {done ? "Course complete 🎉" : "Your progress"}
                        </span>
                        <span className="text-sm font-bold text-indigo-600 tabular-nums">{pct}%</span>
                      </div>
                      <div className="h-2.5 w-full rounded-full bg-slate-100 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${done ? "bg-emerald-500" : "bg-indigo-600"}`}
                          style={{ width: `${pct}%` }}
                          role="progressbar"
                          aria-valuenow={pct}
                          aria-valuemin={0}
                          aria-valuemax={100}
                        />
                      </div>
                      <p className="text-xs text-slate-500 mt-1.5">
                        {progress
                          ? `${progress.completed} of ${progress.total} lessons complete`
                          : "Loading progress…"}
                      </p>
                    </div>
                  );
                })()}
                <Link href={firstLessonId ? `/courses/${c.slug}/lessons/${firstLessonId}` : `/courses/${c.slug}`}
                      className="block w-full text-center px-4 py-3 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700 shadow-sm transition-colors">
                  {progress && progress.completed > 0 ? "Continue learning" : "Start learning"}
                </Link>
                <Link href={`/courses/${c.slug}/podcast`}
                      className="mt-2 flex items-center justify-center gap-2 w-full px-4 py-3 bg-white border border-slate-300 text-slate-700 text-sm font-semibold rounded-lg hover:bg-slate-50 transition-colors">
                  🎧 Listen as podcast
                </Link>
              </>
            ) : (
              <>
                <div className="text-3xl font-bold text-slate-900 mb-3">
                  {c.enrollment_type === "free"
                    ? "Free"
                    : `${c.currency} ${(c.base_price_paise / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
                </div>
                {/* Social-proof signal: only render once we have a count
                    (avoid showing "0 enrolled" pre-load — looks worse than
                    no signal at all). */}
                {typeof detail.enrollment_count === "number" && detail.enrollment_count > 0 && (
                  <div className="text-xs text-slate-500 mb-3" aria-live="polite">
                    <strong className="text-slate-700">{detail.enrollment_count.toLocaleString()}</strong>{" "}
                    {detail.enrollment_count === 1 ? "learner" : "learners"} enrolled
                  </div>
                )}
                {me === undefined ? (
                  <div className="h-12 bg-slate-100 rounded-lg animate-pulse" />
                ) : me === null ? (
                  <button onClick={() => router.push(`/login?next=/courses/${c.slug}`)}
                          data-track="cta:course_sign_in_to_enrol"
                          className="w-full px-4 py-3 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700 shadow-sm transition-colors">
                    Sign in to enrol
                  </button>
                ) : c.enrollment_type === "free" ? (
                  <button onClick={selfEnroll}
                          data-track="cta:course_enrol_free"
                          className="w-full px-4 py-3 bg-emerald-600 text-white text-sm font-semibold rounded-lg hover:bg-emerald-700 shadow-sm transition-colors">
                    Enrol for free
                  </button>
                ) : (
                  <button
                    onClick={() => router.push("/pricing")}
                    data-track="cta:course_get_access"
                    className="w-full px-4 py-3 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700 shadow-sm transition-colors">
                    Get access
                  </button>
                )}
              </>
            )}
            {c.target_audience && (
              <p className="text-xs text-slate-500 mt-4 leading-relaxed">{c.target_audience}</p>
            )}
          </aside>
        </header>

        {/* Announcements (enrolled only) */}
        {announcements.length > 0 && (
          <section className="mb-8 space-y-2">
            <h2 className="font-semibold text-slate-900">Announcements</h2>
            {announcements.map((a) => (
              <div key={a.id} className="bg-indigo-50 border border-indigo-200 rounded-lg p-4">
                <div className="text-sm font-semibold text-indigo-900">{a.title}</div>
                <p className="text-sm text-slate-700 mt-1 whitespace-pre-wrap">{a.body}</p>
              </div>
            ))}
          </section>
        )}

        {/* Curriculum */}
        <section className="mb-8">
          <h2 className="text-xl font-bold text-slate-900 mb-4">Curriculum</h2>
          <div className="space-y-3">
            {detail.chapters.map((ch, ci) => (
              <div key={ch.id} className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <div className="px-4 py-3 bg-slate-50 border-b border-slate-200">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-500 font-mono text-xs">{ci + 1}</span>
                    <h3 className="font-semibold text-slate-900">{ch.title}</h3>
                    {ch.is_mandatory && (
                      <span className="px-1.5 py-0.5 text-[10px] font-bold uppercase bg-indigo-100 text-indigo-700 rounded">
                        Mandatory
                      </span>
                    )}
                  </div>
                  {ch.description && <p className="text-xs text-slate-600 mt-1">{ch.description}</p>}
                </div>
                <ul className="divide-y divide-slate-100">
                  {ch.lessons.map((l, li) => {
                    const canOpen = detail.is_enrolled || l.is_free_preview;
                    const icon =
                      l.lesson_type === "video"     ? "▶" :
                      l.lesson_type === "quiz"      ? "✓" :
                      l.lesson_type === "checklist" ? "☑" : "📄";
                    return (
                      <li key={l.id}
                          className={`px-4 py-3 ${canOpen ? "hover:bg-slate-50" : ""}`}>
                        <div className="flex items-center justify-between">
                          {canOpen ? (
                            <Link href={`/courses/${c.slug}/lessons/${l.id}`}
                                  className="flex items-center gap-3 text-sm flex-1">
                              <span className="text-slate-400">{icon}</span>
                              <span className="text-slate-500 font-mono text-xs">
                                {ci + 1}.{li + 1}
                              </span>
                              <span className="text-slate-900 hover:text-indigo-700 hover:underline">
                                {l.title}
                              </span>
                              {l.is_free_preview && (
                                <span className="px-1.5 py-0.5 text-[10px] font-bold uppercase bg-emerald-100 text-emerald-700 rounded">
                                  Preview
                                </span>
                              )}
                            </Link>
                          ) : (
                            <div className="flex items-center gap-3 text-sm flex-1 text-slate-500">
                              <span>{icon}</span>
                              <span className="font-mono text-xs">{ci + 1}.{li + 1}</span>
                              <span>{l.title}</span>
                              <span className="text-slate-400 text-xs">🔒</span>
                            </div>
                          )}
                          {l.duration_seconds && (
                            <span className="text-xs text-slate-500 font-mono">
                              {Math.floor(l.duration_seconds / 60)}:{String(l.duration_seconds % 60).padStart(2, "0")}
                            </span>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
        </section>

        {/* Reviews */}
        {reviews.length > 0 && (
          <section className="mb-8">
            <h2 className="text-xl font-bold text-slate-900 mb-4">Reviews</h2>
            <div className="space-y-3">
              {reviews.slice(0, 5).map((r) => (
                <div key={r.id} className="bg-white border border-slate-200 rounded-lg p-4">
                  <div className="flex items-center gap-1 text-amber-500">
                    {"★".repeat(r.stars)}
                    <span className="text-slate-300">{"★".repeat(5 - r.stars)}</span>
                  </div>
                  {r.body && <p className="text-sm text-slate-700 mt-2">{r.body}</p>}
                </div>
              ))}
            </div>
          </section>
        )}
      </main>
      <SiteFooter />
    </>
  );
}
