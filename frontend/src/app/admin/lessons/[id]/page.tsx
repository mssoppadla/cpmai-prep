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
import { admin, errMsg, absoluteUploadUrl } from "@/lib/api";
import VideoCompressDialog from "@/components/lms/VideoCompressDialog";
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
  const [courseId, setCourseId] = useState<number | null>(null);
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
        const l = await admin.lms.getLesson(lessonId);
        setLesson(l);
        setCourseId(l.course_id ?? null);
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
        // Load existing files. Wrapped in its own try so a transient
        // files-API hiccup doesn't block the lesson editor from opening
        // — but we DO surface the error to the toolbar so the admin
        // knows the file list shown is incomplete, instead of silently
        // showing an empty Attached Files panel that hides existing
        // uploads.
        try {
          const fs = await admin.lms.listLessonFiles(lessonId);
          setFiles(fs);
        } catch (fe) {
          console.error("[lesson editor] files", fe);
          setErr(`Could not load attached files: ${errMsg(fe)}. The lesson opened but the file list may be incomplete — refresh to retry.`);
        }
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

  const [uploading, setUploading] = useState(false);

  async function addFile(picked: File, category: FileCategory) {
    setUploading(true); setErr(null);
    try {
      // 1. Upload to backend → get hosted URL
      const uploaded = await admin.uploads.file(picked);
      // 2. Create the LessonFile row pointing at that URL
      const f = await admin.lms.addFile(lessonId, {
        filename: uploaded.filename,
        file_url: uploaded.url,
        file_size_bytes: uploaded.size_bytes,
        mime_type: uploaded.mime_type,
        file_category: category,
      });
      setFiles((prev) => [...prev, f]);
    } catch (e) { setErr(errMsg(e)); }
    finally { setUploading(false); }
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
          {/* Back to THE course this lesson belongs to (not the courses
           *  index) — preserves the operator's place when navigating
           *  between lessons. Falls back to /admin/courses if for some
           *  reason course_id wasn't resolved (shouldn't happen). */}
          <Link href={courseId !== null ? `/admin/courses/${courseId}` : "/admin/courses"}
                className="text-xs text-slate-500 hover:underline">
            ← Back to course
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
              <VideoUploadField
                videoUrl={meta.video_url ?? null}
                videoProvider={meta.video_provider ?? null}
                onUploaded={(url) => onMeta({ video_url: url, video_provider: "r2" })}
                onClear={() => onMeta({ video_url: null })}
              />
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Or paste a video URL (YouTube, Vimeo, etc.)
                </label>
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
          <FileAttachmentsSection files={files}
                                  uploading={uploading}
                                  onUpload={addFile}
                                  onDelete={deleteFile} />
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
            <label className="block text-xs font-medium text-slate-700 mb-1">
              Discussion URL (overrides course default)
            </label>
            <input value={meta.discussion_url ?? ""}
                   onChange={(e) => onMeta({ discussion_url: e.target.value || null })}
                   placeholder="(leave blank to inherit from course)"
                   className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono" />
            <p className="text-xs text-slate-500 mt-1">
              Blank = the course&apos;s default Discord/forum URL is used.
              Set this only if this specific lesson needs a different
              discussion link.
            </p>
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


// ============================================================ Video upload field

function VideoUploadField({
  videoUrl, videoProvider, onUploaded, onClear,
}: {
  videoUrl: string | null;
  videoProvider: string | null;
  onUploaded: (url: string) => void;
  onClear: () => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // The compress dialog opens immediately on file pick. It re-encodes
  // entirely client-side via MediaRecorder, or the admin can skip
  // straight to upload-original. Either way, the resulting File goes
  // through the same admin.uploads.file path.
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const isR2 = videoProvider === "r2" && videoUrl?.startsWith("/uploads/");

  async function actuallyUpload(file: File) {
    setErr(null); setUploading(true);
    try {
      const uploaded = await admin.uploads.file(file);
      onUploaded(uploaded.url);
    } catch (e) {
      setErr(errMsg(e));
    } finally { setUploading(false); }
  }

  function handleFile(file: File) {
    if (!file.type.startsWith("video/")) {
      setErr("Please select a video file (.mp4, .webm, .mov)");
      return;
    }
    setErr(null);
    setPendingFile(file);   // opens the compress dialog
  }

  return (
    <div>
      <label className="block text-xs font-medium text-slate-700 mb-1">
        Upload video file (stored on server)
      </label>
      {isR2 && videoUrl && (
        <div className="mb-2 bg-emerald-50 border border-emerald-200 rounded-lg p-3 flex items-center justify-between text-sm">
          <span className="text-emerald-900">
            ✓ Uploaded: <code className="font-mono text-xs">{videoUrl.split("/").pop()}</code>
          </span>
          <button onClick={onClear}
                  className="text-rose-600 hover:underline text-xs">
            Remove
          </button>
        </div>
      )}
      <label
        className={`block border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition ${
          uploading
            ? "border-amber-400 bg-amber-50 cursor-wait"
            : "border-slate-300 hover:border-indigo-300 hover:bg-slate-50"
        }`}>
        <input type="file" accept="video/*"
               disabled={uploading}
               onChange={(e) => {
                 const f = e.target.files?.[0];
                 if (f) void handleFile(f);
               }}
               className="hidden" />
        <div className="text-sm text-slate-700">
          {uploading ? (
            "Uploading… (may take a few minutes for hour-long lectures)"
          ) : (
            <>
              <strong>Click to upload</strong> a video file
              <div className="text-xs text-slate-500 mt-1">
                MP4, WebM, MOV — up to 1 GB. A compression step opens
                automatically so you can shrink before upload.
              </div>
            </>
          )}
        </div>
      </label>
      {err && <p className="text-xs text-rose-600 mt-2">{err}</p>}
      {pendingFile && (
        <VideoCompressDialog
          file={pendingFile}
          onUseCompressed={(f) => { setPendingFile(null); void actuallyUpload(f); }}
          onUseOriginal={(f) => { setPendingFile(null); void actuallyUpload(f); }}
          onCancel={() => setPendingFile(null)}
        />
      )}
    </div>
  );
}


// ============================================================ File attachments section

function FileAttachmentsSection({
  files, uploading, onUpload, onDelete,
}: {
  files: LessonFileOut[];
  uploading: boolean;
  onUpload: (file: File, category: FileCategory) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  const [category, setCategory] = useState<FileCategory>("reference");
  const [dragging, setDragging] = useState(false);
  // Pull the server-side cap so the picker hint stays accurate even
  // if MAX_UPLOAD_MB is bumped on the VPS. One fetch on mount; fall
  // back to the conservative 100 MB display if the config endpoint
  // fails (unauth users wouldn't see this section anyway).
  const [maxMb, setMaxMb] = useState<number>(1024);
  useEffect(() => {
    admin.uploads.config().then((c) => setMaxMb(c.max_mb)).catch(() => {});
  }, []);

  async function handleFiles(list: FileList | null) {
    if (!list || list.length === 0) return;
    // Upload each file in sequence so progress feels deterministic
    for (let i = 0; i < list.length; i++) {
      await onUpload(list[i], category);
    }
  }

  function isImage(mime: string | null | undefined): boolean {
    return !!mime && mime.startsWith("image/");
  }

  return (
    <section className="bg-white border border-slate-200 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3 gap-3">
        <h2 className="font-semibold text-slate-900">Attached files</h2>
        <div className="flex items-center gap-2 text-xs">
          <label className="text-slate-600">Category:</label>
          <select value={category}
                  onChange={(e) => setCategory(e.target.value as FileCategory)}
                  className="px-2 py-1 border border-slate-300 rounded">
            <option value="assignment">Assignment</option>
            <option value="reference">Reference</option>
            <option value="starter_code">Starter code</option>
            <option value="solution">Solution</option>
          </select>
        </div>
      </div>

      <label
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void handleFiles(e.dataTransfer.files);
        }}
        className={`block border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition ${
          dragging ? "border-indigo-500 bg-indigo-50"
                   : "border-slate-300 hover:border-indigo-300 hover:bg-slate-50"
        } ${uploading ? "opacity-60 cursor-wait" : ""}`}>
        <input type="file" multiple
               disabled={uploading}
               onChange={(e) => void handleFiles(e.target.files)}
               className="hidden" />
        <div className="text-sm text-slate-700">
          {uploading ? "Uploading…" : (
            <>
              <strong>Drop files here</strong> or click to select
              <div className="text-xs text-slate-500 mt-1">
                PDFs, images, datasets, starter code, slides. Up to {maxMb >= 1024 ? `${(maxMb/1024).toFixed(0)} GB` : `${maxMb} MB`} each.
              </div>
            </>
          )}
        </div>
      </label>

      {files.length > 0 && (
        <ul className="divide-y divide-slate-100 mt-3">
          {files.map((f) => (
            <li key={f.id} className="flex items-center justify-between py-2 text-sm gap-3">
              <div className="flex items-center gap-3 min-w-0">
                {isImage(f.mime_type) && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={absoluteUploadUrl(f.file_url)}
                    alt={f.filename}
                    className="w-12 h-12 object-cover rounded border border-slate-200 flex-shrink-0"
                    loading="lazy"
                  />
                )}
                <div className="min-w-0">
                  <a href={absoluteUploadUrl(f.file_url)}
                     target="_blank" rel="noopener noreferrer"
                     className="text-indigo-700 hover:underline truncate block">
                    {f.filename}
                  </a>
                  <div>
                    <span className="text-xs text-slate-500">[{f.file_category}]</span>
                    {f.file_size_bytes && (
                      <span className="ml-2 text-xs text-slate-400">
                        {f.file_size_bytes >= 1024 * 1024
                          ? `${(f.file_size_bytes / (1024 * 1024)).toFixed(1)} MB`
                          : `${(f.file_size_bytes / 1024).toFixed(0)} KB`}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <button onClick={() => onDelete(f.id)}
                      className="text-rose-600 hover:underline text-xs flex-shrink-0">
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
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
      // Hydrate options-per-question in parallel so the builder can
      // SHOW existing options (not just append new ones). Each request
      // is independent; Promise.all settles after the last one. We
      // accept partial failures — if one question's options 500s the
      // others still render — but log so a broken endpoint isn't silent.
      const entries = await Promise.all(
        qs.filter((q) => q.question_type !== "short_answer").map(async (q) => {
          try {
            const opts = await admin.lms.listQuizOptions(q.id);
            return [q.id, opts] as const;
          } catch (e) {
            console.error(`[quiz builder] options for Q${q.id}`, e);
            return [q.id, []] as const;
          }
        }),
      );
      setOptionsByQ(Object.fromEntries(entries));
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
      // Drop the now-orphaned options from local state too. The
      // delete endpoint cascades server-side, but we don't refetch.
      setOptionsByQ((prev) => {
        const next = { ...prev };
        delete next[qid];
        return next;
      });
    } catch (e) { onError(errMsg(e)); }
  }

  async function deleteOption(qid: number, oid: number) {
    if (!confirm("Delete this option?")) return;
    try {
      await admin.lms.deleteQuizOption(oid);
      setOptionsByQ((prev) => ({
        ...prev,
        [qid]: (prev[qid] ?? []).filter((o) => o.id !== oid),
      }));
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
                  <span className="flex-1">{o.text}</span>
                  <button
                    onClick={() => deleteOption(q.id, o.id)}
                    className="text-rose-600 hover:underline"
                    aria-label={`Delete option ${o.text}`}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}
