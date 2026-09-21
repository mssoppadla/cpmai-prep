"use client";
/**
 * Question editor form — used in two places:
 *   - the side panel on /admin/questions (edit in place, filters stay put);
 *   - the standalone /admin/questions/[id] page (deep links, "new").
 *
 * The form owns its state and tells the host two things: whether it has
 * unsaved edits (`onDirtyChange`) and when a save landed (`onSaved`, with
 * the server row). The host can also force a save through the ref
 * (`save()` → true when the row persisted) — that's what the "Save &
 * switch" prompt on the list page uses.
 */
import {
  forwardRef, useEffect, useImperativeHandle, useMemo, useState,
} from "react";
import { admin, content as contentApi, errMsg } from "@/lib/api";
import { RichTextEditor } from "@/components/RichText";
import type {
  Difficulty, DomainOut, QuestionAdminIn, QuestionAdminOut, QuestionOptionIn, QuestionType,
} from "@/types/api";

const LETTERS = ["A", "B", "C", "D", "E", "F"];
const blankOption = (i: number): QuestionOptionIn => ({
  option_letter: LETTERS[i], text: "", is_correct: false, reasoning: "",
});
const EMPTY: QuestionAdminIn = {
  stem: "", topic_id: 0,
  domain: "", task: "", enablers: [], remarks: "",
  difficulty: "medium",
  question_type: "single_choice",
  explanation: "",
  options: [blankOption(0), blankOption(1), blankOption(2), blankOption(3)],
  is_active: true,
};

function fromRow(q: QuestionAdminOut): QuestionAdminIn {
  return {
    stem: q.stem, topic_id: q.topic_id,
    domain: q.domain ?? "", task: q.task ?? "",
    enablers: q.enablers ?? [],
    remarks: q.remarks ?? "",
    difficulty: q.difficulty ?? "medium",
    question_type: q.question_type ?? "single_choice",
    explanation: q.explanation ?? "",
    options: q.options.map(o => ({
      option_letter: o.option_letter, text: o.text,
      is_correct: o.is_correct ?? false, reasoning: o.reasoning ?? "",
    })),
    is_active: q.is_active ?? true,
  };
}

/** Stable serialisation for dirty checks (enablers compared as text). */
function snapshot(form: QuestionAdminIn, enablersText: string): string {
  return JSON.stringify({ ...form, enablers: undefined, enablersText: enablersText.trim() });
}

export interface QuestionEditorHandle {
  /** Persist the current form. Resolves true when saved, false when the
   *  form is invalid or the request failed (error shown inline). */
  save(): Promise<boolean>;
  isDirty(): boolean;
}

export const QuestionEditorForm = forwardRef<QuestionEditorHandle, {
  /** Question id, or "new". Changing it loads the other question. */
  questionId: number | "new";
  onSaved?: (row: QuestionAdminOut, wasNew: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onCancel?: () => void;
  /** Tighter spacing for the side panel. */
  compact?: boolean;
  /** Extra buttons rendered next to Save (e.g. "Close"). */
  footerExtra?: React.ReactNode;
}>(function QuestionEditorForm(
  { questionId, onSaved, onDirtyChange, onCancel, compact = false, footerExtra }, ref,
) {
  const isNew = questionId === "new";
  const [topics, setTopics] = useState<Array<{id:number;code:string;name:string}>>([]);
  const [domains, setDomains] = useState<DomainOut[]>([]);
  const [form, setForm] = useState<QuestionAdminIn>(EMPTY);
  const [enablersText, setEnablersText] = useState("");
  const [loading, setLoading] = useState(!isNew);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  // What the form looked like when it was loaded / last saved (state, not
  // a ref: the dirty flag must recompute the moment a save lands).
  const [baseline, setBaseline] = useState<string>(() => snapshot(EMPTY, ""));

  useEffect(() => {
    contentApi.topics().then(setTopics).catch(() => {});
    contentApi.domains().then(setDomains).catch(() => {});
  }, []);

  // (Re)load whenever the target question changes.
  useEffect(() => {
    let alive = true;
    setErr(null); setSavedAt(null);
    if (isNew) {
      const f = { ...EMPTY, topic_id: topics[0]?.id ?? 0 };
      setForm(f); setEnablersText(""); setLoading(false);
      setBaseline(snapshot(f, ""));
      return;
    }
    setLoading(true);
    admin.questions.get(questionId)
      .then(q => {
        if (!alive) return;
        const f = fromRow(q), et = (q.enablers ?? []).join(", ");
        setForm(f); setEnablersText(et);
        setBaseline(snapshot(f, et));
      })
      .catch((e) => { if (alive) setErr(errMsg(e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // topics only matter for the "new" default; don't reload on topic fetch
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionId, isNew]);

  useEffect(() => {
    if (isNew && form.topic_id === 0 && topics.length > 0) {
      const f = { ...form, topic_id: topics[0].id };
      setForm(f); setBaseline(snapshot(f, enablersText));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topics, isNew]);

  const dirty = useMemo(
    () => !loading && snapshot(form, enablersText) !== baseline,
    [form, enablersText, loading, baseline],
  );
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);

  function setOption(i: number, patch: Partial<QuestionOptionIn>) {
    setForm(f => ({ ...f, options: f.options.map((o, j) => j === i ? { ...o, ...patch } : o) }));
  }
  function setCorrect(i: number) {
    setForm(f => ({ ...f, options: f.options.map((o, j) => ({ ...o, is_correct: j === i })) }));
  }
  function toggleCorrect(i: number) {
    setForm(f => ({ ...f, options: f.options.map((o, j) => j === i ? { ...o, is_correct: !o.is_correct } : o) }));
  }
  function setQuestionType(qt: QuestionType) {
    setForm(f => {
      if (qt === "single_choice") {
        let firstChecked = f.options.findIndex(o => o.is_correct);
        if (firstChecked === -1) firstChecked = 0;
        return { ...f, question_type: qt,
                 options: f.options.map((o, j) => ({ ...o, is_correct: j === firstChecked })) };
      }
      return { ...f, question_type: qt };
    });
  }
  function addOption() {
    if (form.options.length >= 6) return;
    setForm(f => ({ ...f, options: [...f.options, blankOption(f.options.length)] }));
  }
  function removeOption(i: number) {
    if (form.options.length <= 2) return;
    setForm(f => ({ ...f, options: f.options.filter((_, j) => j !== i)
      .map((o, j) => ({ ...o, option_letter: LETTERS[j] })) }));
  }

  const selectedTopicCode = topics.find(t => t.id === form.topic_id)?.code;
  const suggestedDomain = selectedTopicCode
    ? domains.find(d => d.phase_codes.includes(selectedTopicCode)) : undefined;
  const correctCount = form.options.filter(o => o.is_correct).length;
  const isMulti = form.question_type === "multi_choice";
  const correctnessOk = isMulti
    ? (correctCount >= 2 && correctCount < form.options.length)
    : (correctCount === 1);
  const validOptions = correctnessOk
    && form.options.every(o => o.text.trim().length > 0)
    && new Set(form.options.map(o => o.option_letter)).size === form.options.length;
  const canSave = form.stem.length >= 10 && form.topic_id > 0 && validOptions;

  async function save(): Promise<boolean> {
    if (!canSave || busy) return false;
    setBusy(true); setErr(null);
    const payload: QuestionAdminIn = {
      ...form,
      enablers: enablersText.split(",").map(s => s.trim()).filter(Boolean),
      domain: form.domain || null,
      task: form.task || null,
      remarks: form.remarks || null,
      explanation: form.explanation || null,
    };
    try {
      const row = isNew
        ? await admin.questions.create(payload)
        : await admin.questions.update(questionId, payload);
      setBaseline(snapshot(form, enablersText));
      setSavedAt(Date.now());
      onDirtyChange?.(false);
      onSaved?.(row, isNew);
      return true;
    } catch (e) {
      console.error("[admin/questions] save failed", e);
      setErr(errMsg(e));
      return false;
    } finally { setBusy(false); }
  }

  useImperativeHandle(ref, () => ({ save, isDirty: () => dirty }), [save, dirty]);

  const pad = compact ? "p-4 space-y-4" : "p-6 space-y-5";
  if (loading) {
    return <div className={`bg-white border border-slate-200 rounded-xl ${pad} text-sm text-slate-500`}>Loading question…</div>;
  }

  return (
    <div className={`bg-white border border-slate-200 rounded-xl ${pad}`}>
      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg text-sm">{err}</div>}

      <div>
        <label className="block text-sm font-medium text-slate-700 mb-1">Question stem</label>
        <textarea value={form.stem} rows={compact ? 4 : 3}
                  onChange={(e) => setForm({ ...form, stem: e.target.value })}
                  placeholder="In CPMAI Phase 2, …"
                  className={input + " font-medium"} />
        <div className="text-xs text-slate-500 mt-1">{form.stem.length} / 4000 chars · min 10</div>
      </div>

      <div className={`grid gap-4 ${compact ? "sm:grid-cols-2" : "sm:grid-cols-2"}`}>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">CPMAI phase</label>
          <select value={form.topic_id || ""}
                  onChange={(e) => setForm({ ...form, topic_id: Number(e.target.value) })}
                  className={input}>
            <option value="">— select —</option>
            {topics.map(t => <option key={t.id} value={t.id}>{t.code} — {t.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Difficulty</label>
          <select value={form.difficulty}
                  onChange={(e) => setForm({ ...form, difficulty: e.target.value as Difficulty })}
                  className={input}>
            <option value="easy">easy</option>
            <option value="medium">medium</option>
            <option value="hard">hard</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Question type</label>
          <select value={form.question_type ?? "single_choice"}
                  onChange={(e) => setQuestionType(e.target.value as QuestionType)}
                  className={input}>
            <option value="single_choice">Single choice (one correct, radio)</option>
            <option value="multi_choice">Multi choice (≥2 correct, checkboxes)</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">ECO domain</label>
          <select value={form.domain ?? ""}
                  onChange={(e) => setForm({ ...form, domain: e.target.value })}
                  className={input}>
            <option value="">— unassigned —</option>
            {domains.map(d => <option key={d.code} value={d.code}>{d.code} — {d.name}</option>)}
            {form.domain && !domains.some(d => d.code === form.domain) && (
              <option value={form.domain}>{form.domain} (legacy — please re-pick)</option>
            )}
          </select>
          {suggestedDomain && form.domain !== suggestedDomain.code && (
            <button type="button"
                    onClick={() => setForm({ ...form, domain: suggestedDomain.code })}
                    className="text-xs text-indigo-600 hover:underline mt-1">
              This phase usually maps to {suggestedDomain.code} — {suggestedDomain.name}. Use it?
            </button>
          )}
          {!compact && (
            <p className="text-xs text-slate-500 mt-1">
              Results &amp; focused practice are grouped by domain. Pick{" "}
              <strong>Trustworthy AI</strong> for cross-cutting questions.
            </p>
          )}
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Task (optional)</label>
          <input value={form.task ?? ""}
                 onChange={(e) => setForm({ ...form, task: e.target.value })}
                 placeholder="Identify and document gaps" className={input} />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Enablers (comma-separated)</label>
          <input value={enablersText}
                 onChange={(e) => setEnablersText(e.target.value)}
                 placeholder="Data profiling, Quality metrics" className={input} />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-700 mb-1">Remarks (admin-only note)</label>
        <input value={form.remarks ?? ""}
               onChange={(e) => setForm({ ...form, remarks: e.target.value })}
               placeholder="Tests Phase 2 vs Phase 3 separation." className={input} />
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-700 mb-1">General explanation (shown after submit)</label>
        <RichTextEditor value={form.explanation ?? ""} minRows={3}
                        placeholder="Explain the concept — formatting, emoji and pasted images supported."
                        onChange={(html) => setForm({ ...form, explanation: html })} />
      </div>

      <div className="border-t border-slate-200 pt-4">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <label className="block text-sm font-medium text-slate-700">Options</label>
            <p className="text-xs text-slate-500">
              {isMulti
                ? "Mark every correct option. ≥2 must be correct AND ≥1 must be wrong. Learners pick all that apply; scoring is exact-set match."
                : "Mark exactly one as correct. Reasoning is shown after submit (correct → why, incorrect → why wrong)."}
            </p>
          </div>
          <button type="button" onClick={addOption} disabled={form.options.length >= 6}
                  className="shrink-0 text-xs px-3 py-1.5 bg-slate-100 hover:bg-slate-200 rounded disabled:opacity-50">
            + Add option
          </button>
        </div>
        {!correctnessOk && (
          <div className="bg-amber-50 border border-amber-200 text-amber-800 text-xs p-2 rounded mb-3">
            {isMulti
              ? `Multi-choice needs ≥2 correct AND ≥1 wrong (currently ${correctCount} correct of ${form.options.length}).`
              : `Exactly one option must be marked correct (currently: ${correctCount}).`}
          </div>
        )}
        <div className="space-y-3">
          {form.options.map((opt, i) => (
            <div key={i} className={`border rounded-lg p-3 ${
              opt.is_correct ? "border-emerald-300 bg-emerald-50/40" : "border-slate-200 bg-white"}`}>
              <div className="flex items-center gap-2 mb-2">
                <span className="w-7 h-7 rounded-full border-2 border-slate-300 flex items-center justify-center font-bold text-xs">
                  {opt.option_letter}
                </span>
                <label className="flex items-center gap-1 text-xs text-slate-700">
                  {isMulti ? (
                    <input type="checkbox" checked={opt.is_correct ?? false} onChange={() => toggleCorrect(i)} />
                  ) : (
                    <input type="radio" name={`correct-${String(questionId)}`}
                           checked={opt.is_correct ?? false} onChange={() => setCorrect(i)} />
                  )}
                  Correct
                </label>
                <div className="flex-1" />
                {form.options.length > 2 && (
                  <button type="button" onClick={() => removeOption(i)}
                          className="text-xs text-rose-600 hover:underline">Remove</button>
                )}
              </div>
              <input value={opt.text}
                     onChange={(e) => setOption(i, { text: e.target.value })}
                     placeholder="Option text" className={input + " mb-2"} />
              <RichTextEditor value={opt.reasoning ?? ""} minRows={2}
                              placeholder={opt.is_correct ? "Why this option is correct…" : "Why this option is wrong…"}
                              onChange={(html) => setOption(i, { reasoning: html })} />
            </div>
          ))}
        </div>
      </div>

      <div className="border-t border-slate-200 pt-4 flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={form.is_active ?? true}
                 onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          Active (available to learners)
        </label>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 mr-1" aria-live="polite">
            {busy ? "Saving…" : dirty ? "Unsaved changes" : savedAt ? "Saved" : ""}
          </span>
          {footerExtra}
          {onCancel && (
            <button type="button" onClick={onCancel}
                    className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50">
              {dirty ? "Discard" : "Close"}
            </button>
          )}
          <button type="button" onClick={() => void save()} disabled={!canSave || busy || (!dirty && !isNew)}
                  className="px-5 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50">
            {busy ? "Saving…" : (isNew ? "Create question" : "Save changes")}
          </button>
        </div>
      </div>
    </div>
  );
});

const input = "w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none";
