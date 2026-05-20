"use client";
/**
 * Admin Lesson Editor at /admin/lessons/[id].
 *
 * Lesson-type-specific UI:
 *   - text:      BlockNote body editor (reuses CMS BlockNoteEditor)
 *   - video:     URL / provider / duration / captions form
 *   - quiz:      quiz config + questions + options builder
 *   - checklist: simple list-of-items editor
 *
 * Common to all types: title/subtitle, mandatory, free_preview,
 * published toggle, attached files manager, discussion URL.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { admin, errMsg } from "@/lib/api";
import type {
  LessonOut, LessonUpdateIn, LessonFileOut, LessonFileCreateIn,
  QuizOut, QuizQuestionOut, QuizOptionOut, QuizQuestionType,
  VideoProvider, FileCategory,
} from "@/types/api";
import type { Block, PartialBlock } from "@blocknote/core";


const BlockNoteEditor = dynamic(
  () => import("@/components/cms/BlockNoteEditor"),
  { ssr: false, loading: () => (
    <div className="rounded-xl bg-white border border-slate-200 p-8 text-center text-slate-400">
      Loading editor…
    </div>
  )},
);

const SAVE_DEBOUNCE_MS = 1500;


export default function LessonEditorPage({
  params,
}: { params: { id: string } }) {
  const lessonId = Number(params.id);

  const [lesson, setLesson] = useState<LessonOut | null>(null);
  const [files, setFiles] = useState<LessonFileOut[]>([]);
  const [meta, setMeta] = useState<LessonUpdateIn | null>(null);
  const [saving, setSaving] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [err, setErr] = useState<string | null>(null);
  const [initialBlocks, setInitialBlocks] = useState<PartialBlock[] | undefined>(undefined);

  // ----------------------------------------------------- load

  useEffect(() => {
    if (!Number.isFinite(lessonId)) { setErr("Invalid lesson id"); return; }
    (async () => {
      try {
        // We don't have a single-lesson admin GET endpoint, so we fetch the
        // public detail via the chapter→course path. Simpler: use the public
        // lesson endpoint? We added admin chapter endpoints but not single-
        // lesson getters. Workaround: use lesson update with empty PATCH to
        // get a snapshot. Cleanest is to add a GET endpoint — for now we
        // PATCH with no fields. (Backend PATCH /lessons/{id} returns updated
        // lesson; empty payload = no-op + returns current.)
        const l = await admin.lms.updateLesson(lessonId, {});
        setLesson(l);
        setMeta({
          title: l.title,
          subtitle: l.subtitle,
          lesson_type: l.lesson_type,
          is_mandatory: l.is_mandatory,
          is_free_preview: l.is_free_preview,
          is_published: l.is_published,
          video_url: l.video_url,
          video_provider: l.video_provider,
          duration_seconds: l.duration_seconds,
          thumbnail_url: l.thumbnail_url,
          captions_url: l.captions_url,
          discussion_url: l.discussion_url,
          checklist_items: l.checklist_items,
        });
        setInitialBlocks(l.body_blocks as PartialBlock[]);
        // Files
        // No dedicated endpoint to list files; we rely on the public
        // course detail OR add later. For Phase 1, files are visible
        // on the lesson record when re-fetched after add.
      } catch (e) {
        console.error("[lesson editor] load", e);
        setErr(errMsg(e));
      }
    })();
  }, [lessonId]);

  // ----------------------------------------------------- save metadata (debounced)

  const blocksRef = useRef<Block[] | null>(null);
  useEffect(() => {
    if (!lesson || !meta) return;
    setSaving("saving");
    const t = setTimeout(async () => {
      try {
        const patch: LessonUpdateIn = { ...meta };
        if (blocksRef.current) patch.body_blocks = blocksRef.current as unknown as LessonUpdateIn["body_blocks"];
        const updated = await admin.lms.updateLesson(lessonId, patch);
        setLesson(updated);
        setSaving("saved");
      } catch (e) {
        console.error("[lesson editor] save", e);
        setErr(errMsg(e));
        setSaving("error");
      }
    }, SAVE_DEBOUNCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta]);

  const onBlocksChange = useCallback((next: Block[]) => {
    blocksRef.current = next;
    setSaving("saving");
    // Trigger the same debounced save loop
    setMeta((m) => (m ? { ...m } : m));
  }, []);

  // ----------------------------------------------------- files

  async function addFile() {
    const filename = prompt("Filename (e.g., assignment.pdf):")?.trim();
    if (!filename) return;
    const file_url = prompt("File URL (paste a hosted link):")?.trim();
    if (!file_url) return;
    const cat = prompt("Category (assignment / reference / starter_code / solution):", "reference")?.trim() as FileCategory | undefined;
    try {
      const f = await admin.lms.addFile(lessonId, {
        filename, file_url,
        file_category: (cat ?? "reference") as FileCategory,
      });
      setFiles((prev) => [...prev, f]);
    } catch (e) { setErr(errMsg(e)); }
  }

  async function deleteFile(id: number) {
    if (!confirm("Remove this file?")) return;
    try {
      await admin.lms.deleteFile(id);
      setFiles((prev) => prev.filter((f) => f.id !== id));
    } catch (e) { setErr(errMsg(e)); }
  }

  // ----------------------------------------------------- render

  if (err && !lesson) {
    return (
      <div className="p-8">
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">{err}</div>
      </div>
    );
  }
  if (!lesson || !meta) return <div className="p-8 text-slate-500 text-sm">Loading…</div>;

  const onMeta = (patch: LessonUpdateIn) => setMeta((m) => (m ? { ...m, ...patch } : m));

  return (
    <div className="p-8 max-w-7xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <Link href={`/admin/courses`} className="text-xs text-slate-500 hover:underline">
            ← Courses
          </Link>
          <h1 className="text-xl font-bold text-slate-900 mt-1">{lesson.title || "(untitled lesson)"}</h1>
          <p className="text-xs text-slate-500 mt-1">
            {lesson.lesson_type} lesson ·{" "}
            {saving === "saving" && <span className="text-amber-600">Saving…</span>}
            {saving === "saved"  && <span className="text-emerald-600">Saved</span>}
            {saving === "error"  && <span className="text-rose-600">Save failed</span>}
            {saving === "idle"   && <span className="text-slate-500">Up to date</span>}
          </p>
        </div>
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">{err}</div>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* ============ Left: type-specific body editor ============ */}
        <main className="lg:col-span-2 space-y-6">
          {lesson.lesson_type === "text" && (
            <section>
              <h2 className="text-sm font-semibold text-slate-700 mb-2">Lesson content</h2>
              <BlockNoteEditor initialBlocks={initialBlocks}
                               onBlocksChange={onBlocksChange}
                               placeholderText="Type the lesson body. Use / for blocks." />
            </section>
          )}

          {lesson.lesson_type === "video" && (
            <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
              <h2 className="font-semibold text-slate-900">Video</h2>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Video URL</label>
                <input value={meta.video_url ?? ""} onChange={(e) => onMeta({ video_url: e.target.value || null })}
                       placeholder="https://youtube.com/watch?v=… or https://example.com/video.mp4"
                       className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono" />
              </div>
              <div className="grid sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">Provider</label>
                  <select value={meta.video_provider ?? "youtube"}
                          onChange={(e) => onMeta({ video_provider: e.target.value as VideoProvider })}
                          className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm">
                    <option value="youtube">YouTube</option>
                    <option value="vimeo">Vimeo</option>
                    <option value="r2">Cloudflare R2</option>
                    <option value="stream">Cloudflare Stream</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">Duration (seconds)</label>
                  <input type="number" value={meta.duration_seconds ?? ""}
                         onChange={(e) => onMeta({ duration_seconds: e.target.value ? Number(e.target.value) : null })}
                         className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Thumbnail URL (optional)</label>
                <input value={meta.thumbnail_url ?? ""}
                       onChange={(e) => onMeta({ thumbnail_url: e.target.value || null })}
                       className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono" />
              </div>
            </section>
          )}

          {lesson.lesson_type === "checklist" && (
            <ChecklistEditor
              items={(meta.checklist_items as Array<{ text: string }>) ?? []}
              onChange={(items) => onMeta({ checklist_items: items })}
            />
          )}

          {lesson.lesson_type === "quiz" && (
            <QuizBuilder lessonId={lesson.id} onError={setErr} />
          )}

          {/* Attached files (all lesson types can have downloadable files) */}
          <section className="bg-white border border-slate-200 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-slate-900">Attached files</h2>
              <button onClick={addFile}
                      className="px-3 py-1.5 bg-indigo-600 text-white text-xs font-medium rounded-lg hover:bg-indigo-700">
                + Add file
              </button>
            </div>
            {files.length === 0 ? (
              <p className="text-xs text-slate-500">
                No files attached. Add downloadable resources (PDFs, datasets, starter code) for students.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {files.map((f) => (
                  <li key={f.id} className="flex items-center justify-between py-2 text-sm">
                    <div>
                      <a href={f.file_url} className="text-indigo-700 hover:underline">{f.filename}</a>
                      <span className="ml-2 text-xs text-slate-500">[{f.file_category}]</span>
                    </div>
                    <button onClick={() => deleteFile(f.id)}
                            className="text-rose-600 hover:underline text-xs">Remove</button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </main>

        {/* ============ Right: metadata panel ============ */}
        <aside className="bg-white border border-slate-200 rounded-xl p-5 space-y-4">
          <h2 className="font-semibold text-slate-900">Lesson settings</h2>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Title</label>
            <input value={meta.title ?? ""} onChange={(e) => onMeta({ title: e.target.value })}
                   className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Subtitle (sidebar text)</label>
            <input value={meta.subtitle ?? ""} onChange={(e) => onMeta({ subtitle: e.target.value || null })}
                   className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Discussion URL (Q&A tab)</label>
            <input value={meta.discussion_url ?? ""}
                   onChange={(e) => onMeta({ discussion_url: e.target.value || null })}
                   placeholder="https://discord.com/channels/…"
                   className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono" />
          </div>
          <label className="flex items-center gap-2 pt-2 border-t border-slate-100">
            <input type="checkbox" checked={meta.is_mandatory ?? true}
                   onChange={(e) => onMeta({ is_mandatory: e.target.checked })} />
            <span className="text-sm">Mandatory</span>
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={meta.is_free_preview ?? false}
                   onChange={(e) => onMeta({ is_free_preview: e.target.checked })} />
            <span className="text-sm">Free preview (visible without enrollment)</span>
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={meta.is_published ?? true}
                   onChange={(e) => onMeta({ is_published: e.target.checked })} />
            <span className="text-sm font-medium">Published</span>
          </label>
        </aside>
      </div>
    </div>
  );
}


// ============================================================ Checklist editor

function ChecklistEditor({
  items, onChange,
}: {
  items: Array<{ text: string }>;
  onChange: (items: Array<{ text: string }>) => void;
}) {
  return (
    <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
      <h2 className="font-semibold text-slate-900">Checklist items</h2>
      {items.length === 0 && (
        <p className="text-xs text-slate-500">
          No items yet. Add tasks the student should tick off to complete this lesson.
        </p>
      )}
      {items.map((it, i) => (
        <div key={i} className="flex gap-2">
          <input value={it.text}
                 onChange={(e) => {
                   const next = items.slice();
                   next[i] = { text: e.target.value };
                   onChange(next);
                 }}
                 className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm" />
          <button onClick={() => onChange(items.filter((_, j) => j !== i))}
                  className="px-2 text-rose-600 hover:underline text-xs">×</button>
        </div>
      ))}
      <button onClick={() => onChange([...items, { text: "" }])}
              className="px-3 py-1.5 bg-white border border-slate-300 text-slate-700 text-xs rounded hover:bg-slate-50">
        + Add item
      </button>
    </section>
  );
}


// ============================================================ Quiz builder

function QuizBuilder({ lessonId, onError }: { lessonId: number; onError: (s: string) => void }) {
  const [config, setConfig] = useState<QuizOut | null>(null);
  const [questions, setQuestions] = useState<QuizQuestionOut[]>([]);
  const [optionsByQ, setOptionsByQ] = useState<Record<number, QuizOptionOut[]>>({});

  const reload = useCallback(async () => {
    try {
      try {
        setConfig(await admin.lms.getQuizConfig(lessonId));
      } catch {
        // No config yet — create default
        setConfig(await admin.lms.upsertQuizConfig(lessonId, {}));
      }
      const qs = await admin.lms.listQuizQuestions(lessonId);
      setQuestions(qs);
      // Loading options would require an endpoint per question; we'd
      // need a "GET /quiz-questions/{id}/options" endpoint. For now,
      // the admin sees questions only — they manage options inline when
      // adding via prompt (multi-step). PR follow-up: add list endpoint
      // to surface existing options.
    } catch (e) { onError(errMsg(e)); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lessonId]);

  useEffect(() => { void reload(); }, [reload]);

  async function addQuestion() {
    const qtype = prompt("Question type (single_choice / multi_choice / true_false / short_answer):", "single_choice")?.trim() as QuizQuestionType;
    if (!qtype) return;
    const text = prompt("Question text:")?.trim();
    if (!text) return;
    try {
      const q = await admin.lms.addQuizQuestion(lessonId, {
        question_type: qtype, question_text: text, points: 1,
      });
      setQuestions((prev) => [...prev, q]);
    } catch (e) { onError(errMsg(e)); }
  }

  async function addOption(qid: number, position: number) {
    const text = prompt("Option text:")?.trim();
    if (!text) return;
    const correct = confirm(`Is "${text}" the correct answer?`);
    try {
      const o = await admin.lms.addQuizOption(qid, {
        text, is_correct: correct, position,
      });
      setOptionsByQ((prev) => ({ ...prev, [qid]: [...(prev[qid] ?? []), o] }));
    } catch (e) { onError(errMsg(e)); }
  }

  async function deleteQuestion(qid: number) {
    if (!confirm("Delete this question?")) return;
    try {
      await admin.lms.deleteQuizQuestion(qid);
      setQuestions((prev) => prev.filter((q) => q.id !== qid));
    } catch (e) { onError(errMsg(e)); }
  }

  if (!config) return <div className="text-slate-500 text-sm">Loading quiz…</div>;

  return (
    <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-slate-900">Quiz builder</h2>
        <button onClick={addQuestion}
                className="px-3 py-1.5 bg-indigo-600 text-white text-xs font-medium rounded-lg hover:bg-indigo-700">
          + Question
        </button>
      </div>
      <div className="grid sm:grid-cols-3 gap-3 text-xs">
        <div>
          <label className="block font-medium text-slate-700 mb-1">Pass threshold (%)</label>
          <input type="number" value={config.pass_threshold_percent} min={0} max={100}
                 onChange={async (e) => {
                   const c = await admin.lms.upsertQuizConfig(lessonId, {
                     pass_threshold_percent: Number(e.target.value),
                   });
                   setConfig(c);
                 }}
                 className="w-full px-2 py-1 border border-slate-300 rounded" />
        </div>
        <div>
          <label className="block font-medium text-slate-700 mb-1">Attempts allowed (blank = ∞)</label>
          <input type="number" value={config.attempts_allowed ?? ""}
                 onChange={async (e) => {
                   const c = await admin.lms.upsertQuizConfig(lessonId, {
                     attempts_allowed: e.target.value ? Number(e.target.value) : null,
                   });
                   setConfig(c);
                 }}
                 className="w-full px-2 py-1 border border-slate-300 rounded" />
        </div>
        <div>
          <label className="block font-medium text-slate-700 mb-1">Time limit (seconds)</label>
          <input type="number" value={config.time_limit_seconds ?? ""}
                 onChange={async (e) => {
                   const c = await admin.lms.upsertQuizConfig(lessonId, {
                     time_limit_seconds: e.target.value ? Number(e.target.value) : null,
                   });
                   setConfig(c);
                 }}
                 className="w-full px-2 py-1 border border-slate-300 rounded" />
        </div>
      </div>
      {questions.length === 0 && (
        <p className="text-xs text-slate-500">No questions yet. Click + Question to add the first one.</p>
      )}
      {questions.map((q, i) => (
        <div key={q.id} className="border border-slate-200 rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm">
              <span className="text-slate-500 font-mono mr-2">Q{i + 1}</span>
              <span className="font-medium">{q.question_text}</span>
              <span className="ml-2 text-xs text-slate-500">[{q.question_type}]</span>
            </div>
            <button onClick={() => deleteQuestion(q.id)}
                    className="text-rose-600 hover:underline text-xs">Delete</button>
          </div>
          {q.question_type !== "short_answer" && (
            <div className="ml-4">
              <button onClick={() => addOption(q.id, (optionsByQ[q.id]?.length ?? 0) + 1)}
                      className="px-2 py-1 bg-white border border-slate-300 text-slate-700 text-xs rounded hover:bg-slate-50">
                + Add option
              </button>
              {(optionsByQ[q.id] ?? []).map((o) => (
                <div key={o.id} className="mt-1 text-xs flex items-center gap-2">
                  {o.is_correct ? (
                    <span className="text-emerald-600">✓</span>
                  ) : (
                    <span className="text-slate-400">○</span>
                  )}
                  <span>{o.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}
