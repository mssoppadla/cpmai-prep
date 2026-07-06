"use client";
/**
 * Admin Courses — list view at /admin/courses.
 *
 * Shows all non-deleted courses, lets admin create new ones (slug +
 * title prompt → POST → redirect to editor), publish toggle, soft-delete.
 *
 * Heavy editing happens at /admin/courses/[id] (chapter + lesson tree).
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { admin, errMsg } from "@/lib/api";
import type { CourseOut, CourseDifficulty, EnrollmentType } from "@/types/api";


const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;


function difficultyBadge(d: CourseDifficulty): string {
  switch (d) {
    case "beginner":     return "bg-emerald-100 text-emerald-800";
    case "intermediate": return "bg-amber-100 text-amber-800";
    case "advanced":     return "bg-rose-100 text-rose-800";
  }
}
function enrollmentBadge(t: EnrollmentType): string {
  switch (t) {
    case "free":                 return "bg-sky-100 text-sky-800";
    case "paid":                 return "bg-indigo-100 text-indigo-800";
    case "subscription_bundle":  return "bg-purple-100 text-purple-800";
  }
}


export default function CoursesAdminPage() {
  const [rows, setRows] = useState<CourseOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newSlug, setNewSlug] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function reload() {
    try { setRows(await admin.lms.listCourses()); }
    catch (e) { console.error("[admin/courses] list", e); setErr(errMsg(e)); }
  }
  useEffect(() => { reload(); }, []);

  async function createCourse() {
    const slug = newSlug.trim();
    const title = newTitle.trim();
    if (!SLUG_RE.test(slug)) {
      setErr("Slug must be lowercase alphanumeric with single dashes (e.g. 'intro-to-python')");
      return;
    }
    if (!title) { setErr("Title is required"); return; }
    setBusy(true); setErr(null);
    try {
      const c = await admin.lms.createCourse({ slug, title });
      router.push(`/admin/courses/${c.id}`);
    } catch (e) {
      console.error("[admin/courses] create", e);
      setErr(errMsg(e));
    } finally { setBusy(false); }
  }

  async function deleteCourse(id: number, slug: string) {
    const ok = confirm(
      `Delete course "${slug}"?\n\nSoft-deletes the course — chapters and ` +
      `lessons remain in DB but disappear from this list and the public catalog.`
    );
    if (!ok) return;
    try {
      await admin.lms.deleteCourse(id);
      await reload();
    } catch (e) {
      console.error("[admin/courses] delete", e);
      setErr(errMsg(e));
    }
  }

  return (
    <div className="p-8 max-w-6xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Courses</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Structured learning courses with chapters and lessons. Each course
            can have video, text, quiz, and checklist lessons; downloadable
            files; and progress tracking per enrolled student.
          </p>
        </div>
        {!creating && (
          <button
            onClick={() => { setCreating(true); setErr(null); }}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
            + New course
          </button>
        )}
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      {creating && (
        <div className="bg-white rounded-xl border-2 border-indigo-200 p-6 mb-6">
          <h2 className="font-semibold text-slate-900 mb-4">Create a new course</h2>
          <label className="block text-sm font-medium text-slate-700 mb-1">Slug</label>
          <input value={newSlug} onChange={(e) => setNewSlug(e.target.value)}
                 placeholder="intro-to-python"
                 className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          <p className="text-xs text-slate-500 mt-1">URL piece for the public catalog.</p>
          <label className="block text-sm font-medium text-slate-700 mb-1 mt-4">Title</label>
          <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
                 placeholder="Intro to Python"
                 className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          <div className="flex gap-2 mt-5">
            <button onClick={createCourse} disabled={busy}
                    className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:bg-slate-300">
              {busy ? "Creating…" : "Create and open editor"}
            </button>
            <button onClick={() => { setCreating(false); setNewSlug(""); setNewTitle(""); setErr(null); }}
                    className="px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </div>
      )}

      {rows === null ? (
        <div className="text-slate-500 text-sm">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-8 text-center text-slate-500">
          No courses yet. Click <strong>+ New course</strong> to create your first one.
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-left">
              <tr>
                <th className="px-4 py-3 font-medium">Title / Slug</th>
                <th className="px-4 py-3 font-medium">Difficulty</th>
                <th className="px-4 py-3 font-medium">Enrollment</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Price</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link href={`/admin/courses/${c.id}`}
                          className="font-medium text-indigo-700 hover:underline">
                      {c.title}
                    </Link>
                    <div className="text-xs text-slate-500 mt-0.5">
                      <code className="px-1 bg-slate-100 rounded">/{c.slug}</code>
                      {c.subtitle && <span className="ml-2">{c.subtitle}</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${difficultyBadge(c.difficulty)}`}>
                      {c.difficulty}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${enrollmentBadge(c.enrollment_type)}`}>
                      {c.enrollment_type.replace("_", " ")}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {c.is_published ? (
                      <span className="text-emerald-700 text-xs font-medium">● Published</span>
                    ) : (
                      <span className="text-slate-500 text-xs font-medium">○ Draft</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-700 text-xs font-mono">
                    {c.enrollment_type === "free"
                      ? "—"
                      : `${c.currency} ${(c.base_price_paise / 100).toFixed(2)}`}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => deleteCourse(c.id, c.slug)}
                            className="text-rose-600 hover:underline text-xs">
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
