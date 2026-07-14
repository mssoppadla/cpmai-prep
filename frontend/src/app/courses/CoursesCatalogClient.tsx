"use client";
/**
 * Public course catalog at /courses.
 *
 * Anyone can browse the catalog. Filter by difficulty. Click a card
 * to navigate to /courses/[slug] for full detail.
 */
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { PlayCircle, X, GraduationCap } from "lucide-react";
import { lmsPublic, errMsg } from "@/lib/api";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import type { CoursePublicOut, CourseDifficulty, CourseCategoryOut } from "@/types/api";


function difficultyBadge(d: CourseDifficulty): string {
  switch (d) {
    case "beginner":     return "bg-emerald-100 text-emerald-800";
    case "intermediate": return "bg-amber-100 text-amber-800";
    case "advanced":     return "bg-rose-100 text-rose-800";
  }
}

function isYouTube(url: string): boolean {
  return /youtube\.com|youtu\.be/.test(url);
}
function ytId(url: string): string | null {
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtu.be")) return u.pathname.slice(1).split("/")[0] || null;
    return u.searchParams.get("v");
  } catch { return null; }
}


export type CourseWithCategories = CoursePublicOut & {
  categories: Array<{ id: number; slug: string; name: string }>;
};


/**
 * Interactive catalog. The SERVER page (./page.tsx) fetches the
 * unfiltered catalog + categories and passes them as initial props so
 * the full course list ships in the crawlable initial HTML; this
 * component only refetches when the visitor changes a filter.
 */
export function CoursesCatalogClient({ initialCourses, initialCategories }: {
  initialCourses: CourseWithCategories[] | null;
  initialCategories: CourseCategoryOut[];
}) {
  const [rows, setRows] = useState<CourseWithCategories[] | null>(initialCourses);
  const [categories, setCategories] = useState<CourseCategoryOut[]>(initialCategories);
  const [err, setErr] = useState<string | null>(null);
  const [difficultyFilter, setDifficultyFilter] = useState<CourseDifficulty | "">("");
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [previewing, setPreviewing] = useState<CourseWithCategories | null>(null);
  const hydratedFromServer = useRef(initialCourses !== null);

  // Categories arrive from the server render; refetch client-side only
  // when the server couldn't provide them (API hiccup at render time).
  useEffect(() => {
    if (initialCategories.length > 0) return;
    lmsPublic.listCategories().then(setCategories).catch((e) => {
      console.error("[courses catalog] categories load failed", e);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // First run with server-provided data: nothing to fetch — the
    // filters are still at their defaults.
    if (hydratedFromServer.current) {
      hydratedFromServer.current = false;
      return;
    }
    (async () => {
      try {
        const courses = await lmsPublic.listCourses({
          ...(difficultyFilter ? { difficulty: difficultyFilter } : {}),
          ...(categoryFilter ? { category: categoryFilter } : {}),
        });
        setRows(courses);
      } catch (e) {
        console.error("[courses catalog]", e);
        setErr(errMsg(e));
      }
    })();
  }, [difficultyFilter, categoryFilter]);

  return (
    <>
      <SiteHeader active="courses" />
      <main className="min-h-screen max-w-6xl mx-auto px-6 py-10">
        <header className="mb-8">
          <h1 className="text-4xl font-bold text-slate-900 mb-2">Courses</h1>
          <p className="text-slate-600">
            Structured, instructor-led learning paths for CPMAI and related topics.
          </p>
        </header>

        <div className="space-y-3 mb-6">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm text-slate-700 w-20">Difficulty:</span>
            {(["", "beginner", "intermediate", "advanced"] as const).map((d) => (
              <button key={d || "all"}
                      onClick={() => setDifficultyFilter(d as CourseDifficulty | "")}
                      className={`px-3 py-1 text-xs rounded-full font-medium ${
                        difficultyFilter === d
                          ? "bg-indigo-600 text-white"
                          : "bg-white border border-slate-300 text-slate-700 hover:bg-slate-50"
                      }`}>
                {d || "All"}
              </button>
            ))}
          </div>
          {categories.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-slate-700 w-20">Topic:</span>
              <button onClick={() => setCategoryFilter("")}
                      className={`px-3 py-1 text-xs rounded-full font-medium ${
                        categoryFilter === ""
                          ? "bg-purple-600 text-white"
                          : "bg-white border border-slate-300 text-slate-700 hover:bg-slate-50"
                      }`}>
                All topics
              </button>
              {categories.map((c) => (
                <button key={c.id}
                        onClick={() => setCategoryFilter(c.slug)}
                        className={`px-3 py-1 text-xs rounded-full font-medium ${
                          categoryFilter === c.slug
                            ? "bg-purple-600 text-white"
                            : "bg-white border border-slate-300 text-slate-700 hover:bg-slate-50"
                        }`}>
                  {c.name}
                </button>
              ))}
            </div>
          )}
        </div>

        {err && (
          <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">{err}</div>
        )}

        {rows === null ? (
          <div className="text-slate-500 text-sm">Loading courses…</div>
        ) : rows.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-xl p-12 text-center text-slate-500">
            No courses available yet. Check back soon!
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {rows.map((c) => (
              <div key={c.id}
                   className="group flex flex-col bg-white border border-slate-200 rounded-xl overflow-hidden hover:shadow-md hover:border-indigo-300 transition">
                {/* Thumbnail: cover image (or clean fallback). If a free-
                    preview video exists, the whole thumbnail plays it; else
                    it links through to the course. */}
                <div className="relative aspect-video w-full bg-gradient-to-br from-indigo-100 to-purple-100">
                  {c.cover_image_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={c.cover_image_url} alt=""
                         loading="lazy" decoding="async"
                         className="absolute inset-0 w-full h-full object-cover" />
                  ) : (
                    <span className="absolute inset-0 grid place-items-center text-indigo-300">
                      <GraduationCap size={48} />
                    </span>
                  )}
                  {c.preview_video_url ? (
                    <>
                      <span className="pointer-events-none absolute top-2 left-2 z-10 px-2 py-0.5 rounded-full bg-white/90 text-[10px] font-semibold uppercase tracking-wide text-emerald-700 shadow-sm">
                        Free preview
                      </span>
                      <button type="button" onClick={() => setPreviewing(c)}
                              aria-label={`Play free preview of ${c.title}`}
                              className="absolute inset-0 z-10 grid place-items-center bg-black/0 hover:bg-black/20 transition">
                        <span className="grid place-items-center w-14 h-14 rounded-full bg-white/90 text-indigo-700 shadow-lg group-hover:scale-105 transition">
                          <PlayCircle size={32} />
                        </span>
                      </button>
                    </>
                  ) : (
                    <Link href={`/courses/${c.slug}`} className="absolute inset-0"
                          aria-label={`View ${c.title}`} />
                  )}
                </div>
                {/* Body links to the course */}
                <Link href={`/courses/${c.slug}`} className="block p-4 flex-1">
                  <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${difficultyBadge(c.difficulty)}`}>
                      {c.difficulty}
                    </span>
                    {c.estimated_hours && (
                      <span className="text-xs text-slate-500">· {c.estimated_hours}h</span>
                    )}
                  </div>
                  <h3 className="font-semibold text-slate-900">{c.title}</h3>
                  {c.subtitle && <p className="text-sm text-slate-600 mt-1">{c.subtitle}</p>}
                  {c.categories && c.categories.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {c.categories.map((cat) => (
                        <span key={cat.id}
                              className="px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide bg-purple-100 text-purple-700 rounded">
                          {cat.name}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="mt-3 text-sm font-mono text-slate-700">
                    {c.enrollment_type === "free"
                      ? "Free"
                      : `${c.currency} ${(c.base_price_paise / 100).toFixed(2)}`}
                  </div>
                </Link>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Free-preview lightbox */}
      {previewing?.preview_video_url && (
        <div role="dialog" aria-modal="true" aria-label="Course preview"
             className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
             onClick={() => setPreviewing(null)}>
          <div className="relative w-full max-w-3xl" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => setPreviewing(null)} aria-label="Close preview"
                    className="absolute -top-9 right-0 text-white/80 hover:text-white">
              <X size={26} />
            </button>
            <div className="aspect-video w-full bg-black rounded-xl overflow-hidden shadow-2xl">
              {isYouTube(previewing.preview_video_url) ? (
                <iframe
                  src={`https://www.youtube-nocookie.com/embed/${ytId(previewing.preview_video_url)}?rel=0&autoplay=1`}
                  className="w-full h-full"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen
                  title={`${previewing.title} preview`}
                />
              ) : (
                // eslint-disable-next-line jsx-a11y/media-has-caption
                <video src={previewing.preview_video_url} controls autoPlay
                       className="w-full h-full bg-black" />
              )}
            </div>
            <div className="mt-3 text-center">
              <div className="text-sm font-semibold text-white">{previewing.title}</div>
              <Link href={`/courses/${previewing.slug}`}
                    className="text-xs text-indigo-300 hover:underline">
                View full course →
              </Link>
            </div>
          </div>
        </div>
      )}

      <SiteFooter />
    </>
  );
}
