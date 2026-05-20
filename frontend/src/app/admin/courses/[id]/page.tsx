"use client";
/**
 * Admin Course Editor at /admin/courses/[id].
 *
 * Two-pane layout:
 *   - Left ~70%: course metadata + chapter/lesson tree (add/rename/delete/reorder)
 *   - Right ~30%: enrollments + announcements + categories summary
 *
 * Lesson detail editing (BlockNote body, video URL, quiz config, etc.)
 * happens on a separate route at /admin/lessons/[id] — kept off this
 * page to avoid a megabyte of editor chrome.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { admin, errMsg } from "@/lib/api";
import type {
  ChapterOut, CourseOut, CourseUpdateIn, LessonOut, LessonType,
  EnrollmentOut, CourseAnnouncementOut, CourseCategoryOut,
} from "@/types/api";


const SAVE_DEBOUNCE_MS = 1500;
const LESSON_TYPE_OPTIONS: { value: LessonType; label: string; icon: string }[] = [
  { value: "text",      label: "Text lesson",  icon: "📄" },
  { value: "video",     label: "Video lesson", icon: "▶" },
  { value: "quiz",      label: "Quiz",         icon: "✓" },
  { value: "checklist", label: "Checklist",    icon: "☑" },
];


export default function CourseEditorPage({
  params,
}: { params: { id: string } }) {
  const router = useRouter();
  const courseId = Number(params.id);

  const [course, setCourse] = useState<CourseOut | null>(null);
  const [chapters, setChapters] = useState<ChapterOut[] | null>(null);
  const [lessonsByCh, setLessonsByCh] = useState<Record<number, LessonOut[]>>({});
  const [enrollments, setEnrollments] = useState<EnrollmentOut[] | null>(null);
  const [announcements, setAnnouncements] = useState<CourseAnnouncementOut[] | null>(null);
  const [allCategories, setAllCategories] = useState<CourseCategoryOut[]>([]);
  const [linkedCategoryIds, setLinkedCategoryIds] = useState<Set<number>>(new Set());

  const [meta, setMeta] = useState<CourseUpdateIn | null>(null);
  const [saving, setSaving] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [err, setErr] = useState<string | null>(null);

  // ----------------------------------------------------- load

  const reload = useCallback(async () => {
    try {
      const c = await admin.lms.getCourse(courseId);
      setCourse(c);
    } catch (e) {
      console.error("[course editor] load", e);
      setErr(errMsg(e));
    }
  }, [courseId]);

  useEffect(() => {
    if (!Number.isFinite(courseId)) { setErr("Invalid course id"); return; }
    reload();
  }, [courseId, reload]);

  useEffect(() => {
    if (course && meta === null) {
      setMeta({
        slug: course.slug,
        title: course.title,
        subtitle: course.subtitle,
        description: course.description,
        difficulty: course.difficulty,
        enrollment_type: course.enrollment_type,
        base_price_paise: course.base_price_paise,
        currency: course.currency,
        estimated_hours: course.estimated_hours,
        completion_threshold_percent: course.completion_threshold_percent,
        discussion_url: course.discussion_url,
        is_published: course.is_published,
      });
    }
  }, [course, meta]);

  // ----------------------------------------------------- save metadata (debounced)

  useEffect(() => {
    if (!course || !meta) return;
    setSaving("saving");
    const t = setTimeout(async () => {
      try {
        const updated = await admin.lms.updateCourse(courseId, meta);
        setCourse(updated);
        setSaving("saved");
      } catch (e) {
        console.error("[course editor] save", e);
        setErr(errMsg(e));
        setSaving("error");
      }
    }, SAVE_DEBOUNCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta]);

  // ----------------------------------------------------- load tree (chapters + lessons)

  const reloadTree = useCallback(async () => {
    if (!course) return;
    try {
      // Dedicated admin endpoint — returns full hierarchy including drafts.
      const tree = await admin.lms.getCourseTree(course.id);
      setChapters(tree.chapters);
      const lmap: Record<number, LessonOut[]> = {};
      for (const ch of tree.chapters) {
        lmap[ch.id] = ch.lessons;
      }
      setLessonsByCh(lmap);
    } catch (e) {
      console.error("[course editor] tree", e);
      setErr(errMsg(e));
    }
  }, [course]);

  useEffect(() => { void reloadTree(); }, [reloadTree]);

  // ----------------------------------------------------- chapter actions

  async function addChapter() {
    if (!course) return;
    const title = prompt("Chapter title (e.g., 'Week 1')")?.trim();
    if (!title) return;
    try {
      await admin.lms.createChapter(course.id, { title });
      await reloadTree();
    } catch (e) { setErr(errMsg(e)); }
  }

  async function renameChapter(ch: ChapterOut) {
    const title = prompt("New chapter title:", ch.title)?.trim();
    if (!title || title === ch.title) return;
    try {
      await admin.lms.updateChapter(ch.id, { title });
      await reloadTree();
    } catch (e) { setErr(errMsg(e)); }
  }

  async function deleteChapter(ch: ChapterOut) {
    if (!confirm(`Delete chapter "${ch.title}" and all its lessons?\n\nSoft-delete; recoverable.`)) return;
    try {
      await admin.lms.deleteChapter(ch.id);
      await reloadTree();
    } catch (e) { setErr(errMsg(e)); }
  }

  async function addLesson(chId: number, lesson_type: LessonType) {
    const title = prompt(`${lesson_type} lesson title:`)?.trim();
    if (!title) return;
    try {
      const l = await admin.lms.createLesson(chId, { lesson_type, title });
      await reloadTree();
      router.push(`/admin/lessons/${l.id}`);
    } catch (e) { setErr(errMsg(e)); }
  }

  async function deleteLesson(l: LessonOut) {
    if (!confirm(`Delete lesson "${l.title}"?`)) return;
    try {
      await admin.lms.deleteLesson(l.id);
      await reloadTree();
    } catch (e) { setErr(errMsg(e)); }
  }

  // ----------------------------------------------------- enrollments + announcements

  const reloadSidebar = useCallback(async () => {
    if (!course) return;
    try {
      setEnrollments(await admin.lms.listEnrollments(course.id));
      setAnnouncements(await admin.lms.listAnnouncements(course.id));
    } catch (e) { console.error("[course editor] sidebar", e); }
  }, [course]);

  useEffect(() => { void reloadSidebar(); }, [reloadSidebar]);

  // Categories — load the global list once + this course's current
  // links, so the chip selector can render the toggled state.
  const reloadCategories = useCallback(async () => {
    if (!course) return;
    try {
      const [all, linked] = await Promise.all([
        admin.lms.listCategories(),
        admin.lms.listCourseCategories(course.id),
      ]);
      setAllCategories(all);
      setLinkedCategoryIds(new Set(linked.map((c) => c.id)));
    } catch (e) { console.error("[course editor] categories", e); }
  }, [course]);
  useEffect(() => { void reloadCategories(); }, [reloadCategories]);

  async function toggleCategory(catId: number) {
    if (!course) return;
    const wasLinked = linkedCategoryIds.has(catId);
    // Optimistic UI flip
    setLinkedCategoryIds((prev) => {
      const next = new Set(prev);
      if (wasLinked) next.delete(catId);
      else next.add(catId);
      return next;
    });
    try {
      if (wasLinked) await admin.lms.unlinkCategory(course.id, catId);
      else           await admin.lms.linkCategory(course.id, catId);
    } catch (e) {
      // Revert on error
      setLinkedCategoryIds((prev) => {
        const next = new Set(prev);
        if (wasLinked) next.add(catId);
        else next.delete(catId);
        return next;
      });
      setErr(errMsg(e));
    }
  }

  async function postAnnouncement() {
    if (!course) return;
    const title = prompt("Announcement title:")?.trim();
    if (!title) return;
    const body = prompt("Announcement body:")?.trim();
    if (!body) return;
    try {
      await admin.lms.createAnnouncement(course.id, { title, body });
      await reloadSidebar();
    } catch (e) { setErr(errMsg(e)); }
  }

  // ----------------------------------------------------- render

  if (err && !course) {
    return (
      <div className="p-8">
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">{err}</div>
        <Link href="/admin/courses" className="inline-block mt-4 text-indigo-600 hover:underline text-sm">
          ← Back to courses
        </Link>
      </div>
    );
  }
  if (!course || !meta) return <div className="p-8 text-slate-500 text-sm">Loading…</div>;

  const onMeta = (patch: CourseUpdateIn) => setMeta((m) => (m ? { ...m, ...patch } : m));

  return (
    <div className="p-8 max-w-7xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <Link href="/admin/courses" className="text-xs text-slate-500 hover:underline">
            ← Courses
          </Link>
          <h1 className="text-xl font-bold text-slate-900 mt-1">{course.title}</h1>
          <p className="text-xs text-slate-500 mt-1">
            <code className="px-1 bg-slate-100 rounded">/{course.slug}</code> ·{" "}
            {saving === "saving" && <span className="text-amber-600">Saving…</span>}
            {saving === "saved"  && <span className="text-emerald-600">Saved</span>}
            {saving === "error"  && <span className="text-rose-600">Save failed</span>}
            {saving === "idle"   && <span className="text-slate-500">Up to date</span>}
          </p>
        </div>
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* ============ Left: metadata + tree ============ */}
        <main className="lg:col-span-2 space-y-6">
          {/* Metadata card */}
          <section className="bg-white border border-slate-200 rounded-xl p-5">
            <h2 className="font-semibold text-slate-900 mb-3">Course details</h2>
            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Title</label>
                <input value={meta.title ?? ""}
                       onChange={(e) => onMeta({ title: e.target.value })}
                       className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Slug</label>
                <input value={meta.slug ?? ""}
                       onChange={(e) => onMeta({ slug: e.target.value })}
                       className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono" />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-xs font-medium text-slate-700 mb-1">Subtitle</label>
                <input value={meta.subtitle ?? ""}
                       onChange={(e) => onMeta({ subtitle: e.target.value || null })}
                       className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-xs font-medium text-slate-700 mb-1">Description</label>
                <textarea value={meta.description ?? ""} rows={3}
                          onChange={(e) => onMeta({ description: e.target.value || null })}
                          className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Difficulty</label>
                <select value={meta.difficulty}
                        onChange={(e) => onMeta({ difficulty: e.target.value as "beginner" | "intermediate" | "advanced" })}
                        className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm">
                  <option value="beginner">Beginner</option>
                  <option value="intermediate">Intermediate</option>
                  <option value="advanced">Advanced</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Enrollment</label>
                <select value={meta.enrollment_type}
                        onChange={(e) => onMeta({ enrollment_type: e.target.value as "free" | "paid" | "subscription_bundle" })}
                        className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm">
                  <option value="free">Free</option>
                  <option value="paid">Paid</option>
                  <option value="subscription_bundle">Subscription bundle</option>
                </select>
              </div>
              {meta.enrollment_type === "paid" && (
                <>
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">Price (paise)</label>
                    <input type="number" value={meta.base_price_paise ?? 0}
                           onChange={(e) => onMeta({ base_price_paise: Number(e.target.value) })}
                           className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono" />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">Currency</label>
                    <input value={meta.currency ?? "INR"}
                           onChange={(e) => onMeta({ currency: e.target.value.toUpperCase().slice(0, 3) })}
                           className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono" />
                  </div>
                </>
              )}
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Estimated hours</label>
                <input type="number" value={meta.estimated_hours ?? ""}
                       onChange={(e) => onMeta({ estimated_hours: e.target.value ? Number(e.target.value) : null })}
                       className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Completion threshold (%)</label>
                <input type="number" min={0} max={100} value={meta.completion_threshold_percent ?? 100}
                       onChange={(e) => onMeta({ completion_threshold_percent: Number(e.target.value) })}
                       className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Discussion URL (default for all lessons)
                </label>
                <input value={meta.discussion_url ?? ""}
                       onChange={(e) => onMeta({ discussion_url: e.target.value || null })}
                       placeholder="https://discord.com/channels/…"
                       className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono" />
                <p className="text-xs text-slate-500 mt-1">
                  Each lesson&apos;s &quot;Ask Questions&quot; tab uses this URL by default.
                  Individual lessons can override their own URL if needed.
                </p>
              </div>
              <label className="sm:col-span-2 flex items-center gap-2 mt-2">
                <input type="checkbox" checked={meta.is_published ?? false}
                       onChange={(e) => onMeta({ is_published: e.target.checked })} />
                <span className="text-sm font-medium">Published (visible in public catalog)</span>
              </label>
            </div>
          </section>

          {/* Categories — chip selector */}
          <section className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-slate-900">Categories</h2>
              <Link href="/admin/course-categories"
                    className="text-xs text-indigo-600 hover:underline">
                Manage categories →
              </Link>
            </div>
            {allCategories.length === 0 ? (
              <p className="text-sm text-slate-500">
                No categories defined yet. Create some in{" "}
                <Link href="/admin/course-categories" className="text-indigo-600 hover:underline">
                  /admin/course-categories
                </Link>{" "}
                to tag this course with topics like &quot;Python&quot;, &quot;AI Engineering&quot;, etc.
              </p>
            ) : (
              <>
                <div className="flex flex-wrap gap-2">
                  {allCategories.map((cat) => {
                    const linked = linkedCategoryIds.has(cat.id);
                    return (
                      <button key={cat.id}
                              onClick={() => toggleCategory(cat.id)}
                              className={`px-3 py-1 text-xs rounded-full font-medium transition ${
                                linked
                                  ? "bg-purple-600 text-white"
                                  : "bg-white border border-slate-300 text-slate-700 hover:bg-purple-50 hover:border-purple-300"
                              }`}>
                        {linked && "✓ "}{cat.name}
                      </button>
                    );
                  })}
                </div>
                <p className="text-xs text-slate-500 mt-3">
                  Categories drive catalog filtering at <code className="px-1 bg-slate-100 rounded">/courses?category=…</code>.
                  Students browse by topic; cards show category badges.
                </p>
              </>
            )}
          </section>

          {/* Chapter + lesson tree */}
          <section className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-slate-900">Curriculum</h2>
              <button onClick={addChapter}
                      className="px-3 py-1.5 bg-indigo-600 text-white text-xs font-medium rounded-lg hover:bg-indigo-700">
                + Chapter
              </button>
            </div>
            {chapters === null ? (
              <div className="text-slate-500 text-sm">Loading curriculum…</div>
            ) : chapters.length === 0 ? (
              <p className="text-slate-500 text-sm">
                No chapters yet. Click <strong>+ Chapter</strong> to add the first section
                (e.g., &quot;Week 1&quot;).
              </p>
            ) : (
              <div className="space-y-3">
                {chapters.map((ch, ci) => (
                  <div key={ch.id} className="border border-slate-200 rounded-lg overflow-hidden">
                    <div className="bg-slate-50 px-3 py-2 flex items-center justify-between">
                      <div className="flex items-center gap-2 text-sm">
                        <span className="text-slate-500 font-mono text-xs">#{ci + 1}</span>
                        <span className="font-medium text-slate-900">{ch.title}</span>
                        {ch.is_mandatory && (
                          <span className="px-1.5 py-0.5 text-[10px] font-bold uppercase bg-indigo-100 text-indigo-700 rounded">
                            Mandatory
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1 text-xs">
                        <button onClick={() => renameChapter(ch)}
                                className="px-2 py-1 text-slate-600 hover:text-indigo-600">
                          Rename
                        </button>
                        <button onClick={() => deleteChapter(ch)}
                                className="px-2 py-1 text-rose-600 hover:underline">
                          Delete
                        </button>
                      </div>
                    </div>
                    <ul className="divide-y divide-slate-100">
                      {(lessonsByCh[ch.id] ?? []).map((l, li) => {
                        const typeOption = LESSON_TYPE_OPTIONS.find((o) => o.value === l.lesson_type);
                        return (
                          <li key={l.id} className="flex items-center justify-between px-3 py-2 hover:bg-slate-50">
                            <Link href={`/admin/lessons/${l.id}`}
                                  className="flex items-center gap-2 text-sm flex-1 group">
                              <span className="text-slate-400">{typeOption?.icon ?? "·"}</span>
                              <span className="text-slate-500 font-mono text-xs">
                                {ci + 1}.{li + 1}
                              </span>
                              <span className="text-slate-900 group-hover:text-indigo-700 group-hover:underline">
                                {l.title}
                              </span>
                              {l.is_free_preview && (
                                <span className="px-1.5 py-0.5 text-[10px] font-bold uppercase bg-emerald-100 text-emerald-700 rounded">
                                  Preview
                                </span>
                              )}
                            </Link>
                            <button onClick={() => deleteLesson(l)}
                                    className="text-rose-600 hover:underline text-xs">
                              Delete
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                    <div className="px-3 py-2 bg-slate-50/50 border-t border-slate-100 flex items-center gap-2">
                      <span className="text-xs text-slate-500">Add lesson:</span>
                      {LESSON_TYPE_OPTIONS.map((opt) => (
                        <button key={opt.value}
                                onClick={() => addLesson(ch.id, opt.value)}
                                className="px-2 py-1 text-xs bg-white border border-slate-300 rounded hover:bg-indigo-50 hover:border-indigo-300">
                          {opt.icon} {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </main>

        {/* ============ Right: enrollments + announcements ============ */}
        <aside className="space-y-6">
          <section className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-slate-900">Enrollments</h2>
              <span className="text-xs text-slate-500">{enrollments?.length ?? 0} students</span>
            </div>
            {enrollments && enrollments.length === 0 && (
              <p className="text-xs text-slate-500">No enrolled students yet.</p>
            )}
            {enrollments && enrollments.slice(0, 8).map((e) => (
              <div key={e.id} className="flex items-center justify-between py-1 text-xs">
                <span>User #{e.user_id}</span>
                <span className="text-slate-500">{e.source}</span>
              </div>
            ))}
          </section>

          <section className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-slate-900">Announcements</h2>
              <button onClick={postAnnouncement}
                      className="px-2 py-1 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-700">
                + Post
              </button>
            </div>
            {announcements && announcements.length === 0 && (
              <p className="text-xs text-slate-500">No announcements yet.</p>
            )}
            {announcements && announcements.slice(0, 5).map((a) => (
              <div key={a.id} className="py-2 border-t border-slate-100 first:border-t-0">
                <div className="text-sm font-medium text-slate-900">{a.title}</div>
                <div className="text-xs text-slate-500 mt-0.5">{a.body.slice(0, 100)}</div>
              </div>
            ))}
          </section>
        </aside>
      </div>
    </div>
  );
}
