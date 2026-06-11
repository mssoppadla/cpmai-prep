"use client";
/**
 * Public course catalog at /courses.
 *
 * Anyone can browse the catalog. Filter by difficulty. Click a card
 * to navigate to /courses/[slug] for full detail.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
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


type CourseWithCategories = CoursePublicOut & {
  categories: Array<{ id: number; slug: string; name: string }>;
};


export default function CoursesCatalogPage() {
  const [rows, setRows] = useState<CourseWithCategories[] | null>(null);
  const [categories, setCategories] = useState<CourseCategoryOut[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [difficultyFilter, setDifficultyFilter] = useState<CourseDifficulty | "">("");
  const [categoryFilter, setCategoryFilter] = useState<string>("");

  // One-time fetch of categories for the filter chips. Categories are
  // a nice-to-have for filtering, not load-critical, so a failure here
  // doesn't block the catalog — but log it so a broken /lms/categories
  // endpoint in prod isn't completely silent (devtools surfaces the
  // error; ops monitoring can scrape via the access log).
  useEffect(() => {
    lmsPublic.listCategories().then(setCategories).catch((e) => {
      console.error("[courses catalog] categories load failed", e);
    });
  }, []);

  useEffect(() => {
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
              <Link key={c.id} href={`/courses/${c.slug}`}
                    className="block bg-white border border-slate-200 rounded-xl overflow-hidden hover:shadow-md hover:border-indigo-300 transition">
                {c.cover_image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={c.cover_image_url} alt="" className="aspect-video w-full object-cover" />
                ) : (
                  <div className="aspect-video w-full bg-gradient-to-br from-indigo-100 to-purple-100 flex items-center justify-center text-5xl">
                    🎓
                  </div>
                )}
                <div className="p-4">
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
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>
      <SiteFooter />
    </>
  );
}
