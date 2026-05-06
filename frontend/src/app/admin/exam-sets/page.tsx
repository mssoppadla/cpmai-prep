"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { admin, errMsg } from "@/lib/api";
import type { ExamSetSummaryOut, ExamSetAdminIn, Difficulty } from "@/types/api";

const blank: ExamSetAdminIn = {
  name: "", slug: "", description: "",
  difficulty: "medium", time_limit_minutes: 90, passing_score: 70,
  is_active: true, is_premium: false, display_order: 100,
};

export default function ExamSetsListPage() {
  const [rows, setRows] = useState<ExamSetSummaryOut[] | null>(null);
  const [form, setForm] = useState<ExamSetAdminIn | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function reload() {
    try { setRows(await admin.examSets.list()); }
    catch (e) { console.error("[admin/exam-sets] list", e); setErr(errMsg(e)); }
  }
  useEffect(() => { reload(); }, []);

  function startEdit(s: ExamSetSummaryOut) {
    setEditingId(s.id);
    setForm({
      name: s.name, slug: s.slug, description: s.description ?? "",
      difficulty: s.difficulty,
      time_limit_minutes: s.time_limit_minutes,
      passing_score: s.passing_score,
      is_active: true,
      is_premium: s.is_premium,
      display_order: 100,
      cover_image_url: s.cover_image_url ?? null,
    });
  }
  function cancelForm() { setForm(null); setEditingId(null); }

  async function saveForm() {
    if (!form) return;
    setBusy(true); setErr(null);
    try {
      if (editingId) {
        await admin.examSets.update(editingId, form);
      } else {
        await admin.examSets.create(form);
      }
      cancelForm();
      await reload();
    } catch (e) {
      console.error("[admin/exam-sets] save", e);
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    if (!confirm("Delete this exam set? Linked questions are preserved.")) return;
    try { await admin.examSets.delete(id); await reload(); }
    catch (e) { console.error("[admin/exam-sets] delete", e); setErr(errMsg(e)); }
  }

  async function togglePremium(s: ExamSetSummaryOut) {
    setBusy(true); setErr(null);
    try {
      // Backend PATCH expects a full ExamSetAdminIn — preserve existing
      // settings and flip is_premium.
      await admin.examSets.update(s.id, {
        name: s.name, slug: s.slug, description: s.description ?? "",
        difficulty: s.difficulty, time_limit_minutes: s.time_limit_minutes,
        passing_score: s.passing_score,
        is_active: true,                           // list endpoint hides inactive; keep on
        is_premium: !s.is_premium,
        display_order: 100,
        cover_image_url: s.cover_image_url ?? null,
      });
      await reload();
    } catch (e) {
      console.error("[admin/exam-sets] toggle premium", e);
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-8 max-w-5xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Exam Sets</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Curate sets of questions for learners to attempt.
          </p>
        </div>
        {!form && (
          <button onClick={() => { setEditingId(null); setForm({ ...blank }); }}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium
                             rounded-lg hover:bg-indigo-700">
            + New Exam Set
          </button>
        )}
      </header>

      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700
                              p-3 rounded-lg mb-4 text-sm">{err}</div>}

      {form && (
        <div className="bg-white rounded-xl border-2 border-indigo-200 p-6 mb-6">
          <h2 className="font-semibold text-slate-900 mb-4">
            {editingId ? `Edit exam set` : "New exam set"}
          </h2>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Name">
              <input value={form.name}
                     onChange={(e) => setForm({ ...form, name: e.target.value })}
                     className={cls} placeholder="Set 1 — Foundations" />
            </Field>
            <Field label="Slug (URL)">
              <input value={form.slug}
                     onChange={(e) => setForm({ ...form, slug: e.target.value })}
                     className={cls} placeholder="set-1-foundations"
                     pattern="^[a-z0-9][a-z0-9-]{0,138}[a-z0-9]$" />
            </Field>
            <Field label="Description" full>
              <textarea value={form.description ?? ""} rows={2}
                        onChange={(e) => setForm({ ...form, description: e.target.value })}
                        className={cls} />
            </Field>
            <Field label="Difficulty">
              <select value={form.difficulty}
                      onChange={(e) => setForm({ ...form, difficulty: e.target.value as Difficulty })}
                      className={cls}>
                <option value="easy">easy</option>
                <option value="medium">medium</option>
                <option value="hard">hard</option>
              </select>
            </Field>
            <Field label="Time limit (minutes)">
              <input type="number" value={form.time_limit_minutes ?? 90}
                     min={5} max={300}
                     onChange={(e) => setForm({ ...form, time_limit_minutes: Number(e.target.value) })}
                     className={cls} />
            </Field>
            <Field label="Passing score (%)">
              <input type="number" value={form.passing_score ?? 70}
                     min={0} max={100}
                     onChange={(e) => setForm({ ...form, passing_score: Number(e.target.value) })}
                     className={cls} />
            </Field>
            <Field label="Display order">
              <input type="number" value={form.display_order ?? 100}
                     onChange={(e) => setForm({ ...form, display_order: Number(e.target.value) })}
                     className={cls} />
            </Field>
          </div>
          <div className="flex items-center gap-4 mt-4">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={form.is_active ?? true}
                     onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
              Active
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={form.is_premium ?? false}
                     onChange={(e) => setForm({ ...form, is_premium: e.target.checked })} />
              Premium (subscription required)
            </label>
          </div>
          <div className="flex items-center gap-3 mt-5">
            <button onClick={saveForm} disabled={busy}
                    className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium
                               rounded-lg hover:bg-indigo-700 disabled:opacity-50">
              {busy
                ? (editingId ? "Saving…" : "Creating…")
                : (editingId ? "Save changes" : "Create")}
            </button>
            <button onClick={cancelForm}
                    className="px-4 py-2 bg-white text-slate-700 text-sm font-medium
                               border border-slate-300 rounded-lg hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </div>
      )}

      {!rows ? <div className="text-slate-500">Loading…</div>
       : rows.length === 0 ? (
         <div className="bg-white rounded-xl border border-slate-200 p-12 text-center
                         text-slate-500">
           No exam sets yet.
         </div>
       ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Slug</th>
                <th className="px-4 py-3">Questions</th>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(s => (
                <tr key={s.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-slate-900">{s.name}</div>
                    {s.description && (
                      <div className="text-xs text-slate-500 mt-0.5 line-clamp-1">
                        {s.description}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">
                    <code className="bg-slate-100 px-1.5 py-0.5 rounded text-xs">
                      {s.slug}
                    </code>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600 tabular-nums">
                    {s.question_count}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600 tabular-nums">
                    <span title="Click Edit to change the countdown duration">
                      ⏱ {s.time_limit_minutes} min
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <button
                      onClick={() => togglePremium(s)}
                      disabled={busy}
                      title={s.is_premium
                        ? "Click to make this set free"
                        : "Click to require a paid subscription"}
                      className={`text-xs px-2 py-0.5 rounded border font-medium transition
                        disabled:opacity-50 ${
                        s.is_premium
                          ? "bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100"
                          : "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100"
                      }`}
                    >
                      {s.is_premium ? "⭐ premium" : "free"}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <button onClick={() => startEdit(s)}
                            className="text-xs text-slate-700 hover:underline mr-3">
                      Edit
                    </button>
                    <Link href={`/admin/exam-sets/${s.id}`}
                          className="text-xs text-indigo-600 hover:underline mr-3">
                      Manage questions
                    </Link>
                    <button onClick={() => remove(s.id)}
                            className="text-xs text-rose-600 hover:underline">
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

const cls = "w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none";

function Field({ label, full, children }: {
  label: string; full?: boolean; children: React.ReactNode;
}) {
  return (
    <div className={full ? "sm:col-span-2" : ""}>
      <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
      {children}
    </div>
  );
}
