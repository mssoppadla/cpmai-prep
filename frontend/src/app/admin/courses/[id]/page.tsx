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
import { admin, errMsg, absoluteUploadUrl } from "@/lib/api";
import type {
  ChapterOut, CourseOut, CourseUpdateIn, LessonOut, LessonType,
  EnrollmentAdminOut, CourseAnnouncementOut, CourseCategoryOut,
  ProgramCourseOut,
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
  const [enrollments, setEnrollments] = useState<EnrollmentAdminOut[] | null>(null);
  const [announcements, setAnnouncements] = useState<CourseAnnouncementOut[] | null>(null);
  const [allCategories, setAllCategories] = useState<CourseCategoryOut[]>([]);
  const [linkedCategoryIds, setLinkedCategoryIds] = useState<Set<number>>(new Set());

  const [meta, setMeta] = useState<CourseUpdateIn | null>(null);
  const [saving, setSaving] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [err, setErr] = useState<string | null>(null);
  const [coverBusy, setCoverBusy] = useState(false);

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
        cover_image_url: course.cover_image_url,
        is_program: course.is_program,
        is_published: course.is_published,
      });
    }
  }, [course, meta]);

  // ----------------------------------------------------- program (included courses)

  const [programCourses, setProgramCourses] = useState<ProgramCourseOut[] | null>(null);
  const [parentPrograms, setParentPrograms] = useState<CourseOut[]>([]);
  const [allCourses, setAllCourses] = useState<CourseOut[]>([]);
  const [programBusy, setProgramBusy] = useState(false);
  const [addCourseId, setAddCourseId] = useState<number | "">("");

  const reloadProgram = useCallback(async () => {
    if (!course) return;
    try {
      if (course.is_program) {
        const [rows, all] = await Promise.all([
          admin.lms.listProgramCourses(course.id),
          admin.lms.listCourses(true),
        ]);
        setProgramCourses(rows);
        setAllCourses(all);
      } else {
        setProgramCourses(null);
        setParentPrograms(await admin.lms.listParentPrograms(course.id));
      }
    } catch (e) { console.error("[course editor] program", e); }
  }, [course]);
  useEffect(() => { void reloadProgram(); }, [reloadProgram]);

  async function saveProgramCourses(next: ProgramCourseOut[]) {
    if (!course) return;
    setProgramBusy(true); setErr(null);
    try {
      setProgramCourses(await admin.lms.setProgramCourses(course.id, {
        courses: next.map((r) => ({ course_id: r.course_id, is_mandatory: r.is_mandatory })),
      }));
    } catch (e) { setErr(errMsg(e)); await reloadProgram(); }
    finally { setProgramBusy(false); }
  }
  function moveProgramCourse(idx: number, dir: -1 | 1) {
    if (!programCourses) return;
    const next = [...programCourses];
    const j = idx + dir;
    if (j < 0 || j >= next.length) return;
    [next[idx], next[j]] = [next[j], next[idx]];
    void saveProgramCourses(next);
  }

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

  // Direct enrollment from the course page — the deterministic lever
  // when one specific user needs access NOW, without touching plans.
  const [enrollOpen, setEnrollOpen] = useState(false);
  const [enrollQuery, setEnrollQuery] = useState("");
  const [enrollMatches, setEnrollMatches] =
    useState<{ id: number; email: string; name: string | null }[]>([]);
  const [enrollBusy, setEnrollBusy] = useState(false);

  useEffect(() => {
    if (!enrollOpen || enrollQuery.trim().length < 2) {
      setEnrollMatches([]);
      return;
    }
    let cancel = false;
    const t = setTimeout(async () => {
      try {
        const users = await admin.users.list({ q: enrollQuery.trim(), limit: 6 });
        if (!cancel) {
          setEnrollMatches(users.map((u) => ({
            id: u.id, email: u.email, name: u.name ?? null })));
        }
      } catch { /* search is best-effort */ }
    }, 300);
    return () => { cancel = true; clearTimeout(t); };
  }, [enrollOpen, enrollQuery]);

  async function directEnroll(userId: number, email: string) {
    if (!course || enrollBusy) return;
    setEnrollBusy(true);
    try {
      await admin.lms.grantEnrollment(course.id, {
        user_id: userId,
        grant_reason: `Direct admin enrollment from course page (${email})`,
      });
      setEnrollOpen(false);
      setEnrollQuery("");
      await reloadSidebar();
    } catch (e) { setErr(errMsg(e)); }
    finally { setEnrollBusy(false); }
  }

  async function revokeEnrollmentRow(id: number, who: string) {
    if (!window.confirm(
      `Revoke ${who}'s enrollment? They lose access to this course ` +
      `immediately (their progress is kept and returns on re-enrollment).`,
    )) return;
    try {
      await admin.lms.revokeEnrollment(id);
      await reloadSidebar();
    } catch (e) { setErr(errMsg(e)); }
  }

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

  async function onCoverFile(file: File) {
    setCoverBusy(true);
    setErr(null);
    try {
      const { url } = await admin.uploads.file(file);  // returns "/uploads/...": an image, public
      onMeta({ cover_image_url: url });                 // autosave picks it up (debounced)
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setCoverBusy(false);
    }
  }

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
              <div className="sm:col-span-2">
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Cover image (catalog thumbnail)
                </label>
                <div className="flex items-start gap-4">
                  <div className="w-40 aspect-video rounded-lg border border-slate-200 overflow-hidden bg-slate-50 grid place-items-center shrink-0">
                    {meta.cover_image_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={absoluteUploadUrl(meta.cover_image_url)} alt="Cover preview"
                           className="w-full h-full object-cover" />
                    ) : (
                      <span className="text-3xl" aria-hidden>🎓</span>
                    )}
                  </div>
                  <div className="flex-1">
                    <input type="file" accept="image/*"
                           onChange={(e) => { const f = e.target.files?.[0]; if (f) void onCoverFile(f); }}
                           className="block text-sm text-slate-600 file:mr-3 file:px-3 file:py-1.5 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100" />
                    <p className="text-xs text-slate-500 mt-1.5">
                      Shown on the courses catalog and course page. Recommended 16:9 (e.g. 1280×720).
                      {coverBusy && <span className="ml-2 text-slate-400">Uploading…</span>}
                    </p>
                    {meta.cover_image_url && (
                      <button type="button" onClick={() => onMeta({ cover_image_url: null })}
                              className="mt-2 text-xs text-rose-600 hover:underline">
                        Remove cover image
                      </button>
                    )}
                  </div>
                </div>
              </div>
              <label className="sm:col-span-2 flex items-center gap-2 mt-2">
                <input type="checkbox" checked={meta.is_published ?? false}
                       onChange={(e) => onMeta({ is_published: e.target.checked })} />
                <span className="text-sm font-medium">Published (visible in public catalog)</span>
              </label>
              <p className="sm:col-span-2 text-xs text-slate-500 -mt-1">
                Unpublished = internal course: hidden from the catalog, sitemap,
                and search engines, but still fully accessible to students you
                enroll (via the Enrollments panel or a plan bundle) — they reach
                it from their dashboard. Publish only when it should be publicly
                discoverable.
              </p>
              <label className="sm:col-span-2 flex items-center gap-2 mt-1">
                <input type="checkbox" checked={meta.is_program ?? false}
                       disabled={parentPrograms.length > 0}
                       onChange={(e) => onMeta({ is_program: e.target.checked })} />
                <span className="text-sm font-medium">Program (wraps other courses)</span>
              </label>
              <p className="sm:col-span-2 text-xs text-slate-500 -mt-1">
                A program is sold and enrolled like any course (free, paid, or via a
                plan) and gives its learners every included course automatically —
                now and whenever you add one later. Courses a learner bought
                separately are never affected.
                {parentPrograms.length > 0 && (
                  <> This course is included in{" "}
                    {parentPrograms.map((p, i) => (
                      <span key={p.id}>{i > 0 && ", "}
                        <Link href={`/admin/courses/${p.id}`} className="text-indigo-600 hover:underline">{p.title}</Link>
                      </span>
                    ))}
                    {" "}— access to it is derived from there; it can&apos;t become a program itself.
                  </>
                )}
              </p>
            </div>
          </section>

          {/* Program: included courses */}
          {course.is_program && (
            <section className="bg-white border border-amber-200 rounded-xl p-5">
              <div className="flex items-center justify-between mb-1 gap-3">
                <h2 className="font-semibold text-slate-900">Included courses</h2>
                <span className="text-xs text-slate-500">{programBusy ? "Saving…" : `${programCourses?.length ?? 0} in program`}</span>
              </div>
              <p className="text-xs text-slate-500 mb-3">
                Learners see them in this order. Changes apply to everyone enrolled
                on their next page load.
              </p>
              {programCourses === null ? (
                <p className="text-sm text-slate-500">Loading…</p>
              ) : programCourses.length === 0 ? (
                <p className="text-sm text-slate-500 mb-3">No courses yet — add the first one below.</p>
              ) : (
                <ol className="divide-y divide-slate-100 border border-slate-200 rounded-lg mb-3">
                  {programCourses.map((r, i) => (
                    <li key={r.course_id} className="flex items-center gap-3 px-3 py-2 text-sm">
                      <span className="w-5 text-xs font-mono text-slate-400">{i + 1}</span>
                      <Link href={`/admin/courses/${r.course_id}`}
                            className="min-w-0 flex-1 font-medium text-slate-900 hover:text-indigo-700 hover:underline truncate">
                        {r.title ?? `Course #${r.course_id}`}
                        {r.is_published === false && (
                          <span className="ml-2 px-1.5 py-0.5 text-[10px] font-bold uppercase bg-slate-100 text-slate-600 rounded">internal</span>
                        )}
                      </Link>
                      <label className="flex items-center gap-1 text-xs text-slate-600">
                        <input type="checkbox" checked={r.is_mandatory} disabled={programBusy}
                               onChange={(e) => void saveProgramCourses(
                                 programCourses.map((x) => x.course_id === r.course_id ? { ...x, is_mandatory: e.target.checked } : x))} />
                        Mandatory
                      </label>
                      <button type="button" disabled={programBusy || i === 0} onClick={() => moveProgramCourse(i, -1)}
                              aria-label="Move up" className="px-1.5 text-slate-500 hover:text-indigo-600 disabled:opacity-30">↑</button>
                      <button type="button" disabled={programBusy || i === programCourses.length - 1} onClick={() => moveProgramCourse(i, 1)}
                              aria-label="Move down" className="px-1.5 text-slate-500 hover:text-indigo-600 disabled:opacity-30">↓</button>
                      <button type="button" disabled={programBusy}
                              onClick={() => { if (confirm(`Remove "${r.title}" from this program? Learners keep any separately bought copy.`)) void saveProgramCourses(programCourses.filter((x) => x.course_id !== r.course_id)); }}
                              className="text-xs text-rose-600 hover:underline">Remove</button>
                    </li>
                  ))}
                </ol>
              )}
              <div className="flex items-center gap-2">
                <select value={addCourseId}
                        onChange={(e) => setAddCourseId(e.target.value ? Number(e.target.value) : "")}
                        aria-label="Course to add"
                        className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm">
                  <option value="">Add a course…</option>
                  {allCourses
                    .filter((c) => c.id !== course.id && !c.is_program
                                && !(programCourses ?? []).some((r) => r.course_id === c.id))
                    .map((c) => (
                      <option key={c.id} value={c.id}>{c.title}{c.is_published ? "" : " (internal)"}</option>
                    ))}
                </select>
                <button type="button" disabled={programBusy || addCourseId === ""}
                        onClick={() => {
                          const c = allCourses.find((x) => x.id === addCourseId);
                          if (!c || !programCourses) return;
                          setAddCourseId("");
                          void saveProgramCourses([...programCourses, {
                            course_id: c.id, position: programCourses.length, is_mandatory: true,
                            title: c.title, slug: c.slug, is_published: c.is_published,
                          }]);
                        }}
                        className="px-3 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50">
                  + Add
                </button>
              </div>
            </section>
          )}

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
            <div className="flex items-center justify-between mb-1">
              <h2 className="font-semibold text-slate-900">Enrollments</h2>
              <button
                onClick={() => setEnrollOpen((o) => !o)}
                className="text-xs px-2 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-700"
              >
                {enrollOpen ? "Cancel" : "+ Enroll user"}
              </button>
            </div>
            {enrollments && (
              <p className="text-xs text-slate-500 mb-3">
                {enrollments.length} student{enrollments.length === 1 ? "" : "s"}
                {enrollments.length > 0 && (
                  <>
                    {" · "}
                    {enrollments.filter((e) => e.source === "subscription").length} via plan
                    {" · "}
                    {enrollments.filter((e) => e.source !== "subscription").length} direct
                  </>
                )}
              </p>
            )}
            {enrollOpen && (
              <div className="mb-3 border border-indigo-200 bg-indigo-50 rounded-lg p-2">
                <input
                  autoFocus
                  value={enrollQuery}
                  onChange={(e) => setEnrollQuery(e.target.value)}
                  placeholder="Search user by email or name…"
                  className="w-full px-2 py-1.5 text-xs border border-slate-300 rounded
                             focus:ring-1 focus:ring-indigo-500 outline-none"
                />
                {enrollMatches.length > 0 && (
                  <div className="mt-1 divide-y divide-slate-100 bg-white border border-slate-200 rounded">
                    {enrollMatches.map((u) => (
                      <button
                        key={u.id}
                        disabled={enrollBusy}
                        onClick={() => directEnroll(u.id, u.email)}
                        className="block w-full text-left px-2 py-1.5 text-xs hover:bg-indigo-50 disabled:opacity-50"
                      >
                        <span className="font-medium text-slate-900">{u.email}</span>
                        {u.name && <span className="text-slate-500"> · {u.name}</span>}
                      </button>
                    ))}
                  </div>
                )}
                <p className="mt-1 text-[10px] text-slate-500">
                  Direct enrollments are independent of plans — they survive
                  plan changes and only end via Revoke here.
                </p>
              </div>
            )}
            {enrollments && enrollments.length === 0 && (
              <p className="text-xs text-slate-500">No enrolled students yet.</p>
            )}
            {enrollments && enrollments.slice(0, 20).map((e) => (
              <div key={e.id} className="py-1.5 text-xs border-t border-slate-100 first:border-t-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-slate-900 truncate">
                    {e.user_email ?? `User #${e.user_id}`}
                  </span>
                  <button
                    onClick={() => revokeEnrollmentRow(e.id, e.user_email ?? `#${e.user_id}`)}
                    className="shrink-0 text-rose-600 hover:text-rose-800"
                    title="Revoke this enrollment — removes the student's access to this course (their progress is kept)"
                  >
                    Revoke
                  </button>
                </div>
                <div className="flex items-center gap-2 mt-0.5 text-slate-500">
                  <span>{e.source === "subscription" ? "via plan"
                         : e.source === "admin_grant" ? "direct" : e.source}</span>
                  {e.source === "subscription" && e.backing_subscription_status && (
                    <span className={
                      e.backing_subscription_status === "live"
                        ? "text-emerald-600"
                        : "text-rose-600"
                    }>
                      sub {e.backing_subscription_status}
                    </span>
                  )}
                  {!e.grants_access_now && (
                    <span className="px-1.5 rounded bg-rose-50 text-rose-700 border border-rose-200">
                      no access now
                    </span>
                  )}
                  {e.expires_at && (
                    <span>until {new Date(e.expires_at).toLocaleDateString()}</span>
                  )}
                </div>
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
