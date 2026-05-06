"use client";
import { useEffect, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type { FaqAdminOut, FaqIn } from "@/types/api";

const blank: FaqIn = {
  question: "", answer: "", display_order: 100, is_active: true,
};

export default function FaqsAdminPage() {
  const [rows, setRows] = useState<FaqAdminOut[] | null>(null);
  const [editing, setEditing] = useState<FaqAdminOut | null>(null);
  const [form, setForm] = useState<FaqIn | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function reload() {
    try { setRows(await admin.faqs.list()); }
    catch (e) { console.error("[admin/faqs] list", e); setErr(errMsg(e)); }
  }
  useEffect(() => { reload(); }, []);

  function startEdit(f: FaqAdminOut) {
    setEditing(f);
    setForm({
      question: f.question, answer: f.answer,
      display_order: f.display_order, is_active: f.is_active,
    });
  }
  function startNew() { setEditing(null); setForm({ ...blank }); }
  function cancel()   { setEditing(null); setForm(null); }

  async function save() {
    if (!form) return;
    setBusy(true); setErr(null);
    try {
      if (editing) await admin.faqs.update(editing.id, form);
      else         await admin.faqs.create(form);
      cancel(); await reload();
    } catch (e) { console.error("[admin/faqs] save", e); setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function remove(id: number) {
    if (!confirm("Delete this FAQ entry?")) return;
    try { await admin.faqs.delete(id); await reload(); }
    catch (e) { console.error("[admin/faqs] delete", e); setErr(errMsg(e)); }
  }

  return (
    <div className="p-8 max-w-4xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">FAQs</h1>
          <p className="text-slate-600 mt-1 text-sm">
            These appear at the bottom of the public landing page.
            Disabled rows are hidden but kept for history.
          </p>
        </div>
        {!form && (
          <button onClick={startNew}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
            + New FAQ
          </button>
        )}
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      {form && (
        <div className="bg-white rounded-xl border-2 border-indigo-200 p-6 mb-6">
          <h2 className="font-semibold text-slate-900 mb-4">
            {editing ? `Edit FAQ #${editing.id}` : "New FAQ"}
          </h2>
          <Field label="Question">
            <input value={form.question}
                   onChange={(e) => setForm({ ...form, question: e.target.value })}
                   className={cls} placeholder="What is the CPMAI certification?" />
          </Field>
          <div className="mt-3" />
          <Field label="Answer">
            <textarea value={form.answer} rows={4}
                      onChange={(e) => setForm({ ...form, answer: e.target.value })}
                      className={cls} />
          </Field>
          <div className="grid sm:grid-cols-2 gap-4 mt-3">
            <Field label="Display order (lower = earlier)">
              <input type="number" value={form.display_order}
                     onChange={(e) => setForm({ ...form, display_order: Number(e.target.value) })}
                     className={cls} />
            </Field>
            <label className="flex items-center gap-2 text-sm text-slate-700 mt-6">
              <input type="checkbox" checked={form.is_active}
                     onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
              Active (visible to public)
            </label>
          </div>
          <div className="flex items-center gap-3 mt-5">
            <button onClick={save} disabled={busy}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50">
              {busy ? "Saving…" : (editing ? "Save changes" : "Create")}
            </button>
            <button onClick={cancel}
              className="px-4 py-2 bg-white text-slate-700 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </div>
      )}

      {!rows ? <div className="text-slate-500">Loading…</div>
       : rows.length === 0 ? (
         <div className="bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-500">
           No FAQs yet — click &quot;+ New FAQ&quot;.
         </div>
       ) : (
        <ul className="space-y-2">
          {rows.map(f => (
            <li key={f.id} className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs text-slate-500">#{f.display_order}</span>
                    {!f.is_active && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
                        hidden
                      </span>
                    )}
                  </div>
                  <div className="font-semibold text-slate-900">{f.question}</div>
                  <div className="text-sm text-slate-600 mt-1 line-clamp-3">{f.answer}</div>
                </div>
                <div className="flex flex-col gap-1 flex-shrink-0">
                  <button onClick={() => startEdit(f)}
                    className="text-xs text-slate-700 hover:underline">Edit</button>
                  <button onClick={() => remove(f.id)}
                    className="text-xs text-rose-600 hover:underline">Delete</button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const cls = "w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none";
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
      {children}
    </div>
  );
}
