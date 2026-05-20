"use client";
/**
 * Admin Course Categories — simple CRUD page at /admin/course-categories.
 *
 * Categories are global-per-tenant taxonomy (Python / AI / etc.) used
 * to filter the public course catalog.
 */
import { useEffect, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type { CourseCategoryOut, CourseCategoryCreateIn } from "@/types/api";


const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;


export default function CourseCategoriesPage() {
  const [rows, setRows] = useState<CourseCategoryOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<CourseCategoryOut | null>(null);
  const [form, setForm] = useState<CourseCategoryCreateIn | null>(null);
  const [busy, setBusy] = useState(false);

  async function reload() {
    try { setRows(await admin.lms.listCategories()); }
    catch (e) { setErr(errMsg(e)); }
  }
  useEffect(() => { reload(); }, []);

  function startNew() {
    setEditing(null);
    setForm({ slug: "", name: "", description: "", display_order: 100 });
  }
  function startEdit(c: CourseCategoryOut) {
    setEditing(c);
    setForm({ slug: c.slug, name: c.name, description: c.description, display_order: c.display_order });
  }
  function cancel() { setEditing(null); setForm(null); }

  async function save() {
    if (!form) return;
    if (!SLUG_RE.test(form.slug)) { setErr("Invalid slug — use lowercase + dashes."); return; }
    if (!form.name.trim()) { setErr("Name required."); return; }
    setBusy(true); setErr(null);
    try {
      if (editing) await admin.lms.updateCategory(editing.id, form);
      else await admin.lms.createCategory(form);
      cancel(); await reload();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function deleteCat(id: number) {
    if (!confirm("Delete this category? Course links are removed (cascade).")) return;
    try { await admin.lms.deleteCategory(id); await reload(); }
    catch (e) { setErr(errMsg(e)); }
  }

  // Swap display_order between two rows so the public catalog re-renders
  // them in the new order. We persist via PATCH on both rows in
  // sequence; on a transient failure mid-swap the second row keeps its
  // old value (visible inconsistency, user retries). Optimistic local
  // update so the UI feels instant.
  async function move(idx: number, direction: -1 | 1) {
    if (!rows) return;
    const j = idx + direction;
    if (j < 0 || j >= rows.length) return;
    const a = rows[idx];
    const b = rows[j];
    const next = [...rows];
    next[idx] = { ...a, display_order: b.display_order };
    next[j] = { ...b, display_order: a.display_order };
    next.sort((x, y) => x.display_order - y.display_order || x.id - y.id);
    setRows(next);
    try {
      await admin.lms.updateCategory(a.id, { display_order: b.display_order });
      await admin.lms.updateCategory(b.id, { display_order: a.display_order });
    } catch (e) {
      setErr(errMsg(e));
      await reload();   // rollback from server truth
    }
  }

  return (
    <div className="p-8 max-w-4xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Course Categories</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Tags for organising courses in the public catalog (Python, Data Science, AI, etc.).
          </p>
        </div>
        {!form && (
          <button onClick={startNew}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
            + New category
          </button>
        )}
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">{err}</div>
      )}

      {form && (
        <div className="bg-white rounded-xl border-2 border-indigo-200 p-6 mb-6 space-y-3">
          <h2 className="font-semibold text-slate-900">{editing ? `Edit "${editing.name}"` : "New category"}</h2>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Slug</label>
            <input value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })}
                   className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Name</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                   className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Description</label>
            <textarea value={form.description ?? ""} rows={2}
                      onChange={(e) => setForm({ ...form, description: e.target.value || null })}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Display order</label>
            <input type="number" value={form.display_order ?? 100}
                   onChange={(e) => setForm({ ...form, display_order: Number(e.target.value) })}
                   className="w-32 px-3 py-2 border border-slate-300 rounded-lg text-sm" />
          </div>
          <div className="flex gap-2">
            <button onClick={save} disabled={busy}
                    className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:bg-slate-300">
              {busy ? "Saving…" : "Save"}
            </button>
            <button onClick={cancel}
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
          No categories yet.
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-left">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Slug</th>
                <th className="px-4 py-3 font-medium">Order</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c, idx) => (
                <tr key={c.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{c.name}</div>
                    {c.description && <div className="text-xs text-slate-500 mt-0.5">{c.description}</div>}
                  </td>
                  <td className="px-4 py-3"><code className="text-xs bg-slate-100 px-1 rounded">{c.slug}</code></td>
                  <td className="px-4 py-3 text-slate-700 font-mono text-xs">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => move(idx, -1)}
                        disabled={idx === 0}
                        aria-label="Move up"
                        className="w-6 h-6 flex items-center justify-center rounded border border-slate-300 hover:bg-slate-100 disabled:opacity-30 disabled:cursor-not-allowed"
                      >↑</button>
                      <button
                        onClick={() => move(idx, 1)}
                        disabled={idx === rows.length - 1}
                        aria-label="Move down"
                        className="w-6 h-6 flex items-center justify-center rounded border border-slate-300 hover:bg-slate-100 disabled:opacity-30 disabled:cursor-not-allowed"
                      >↓</button>
                      <span className="ml-2 text-slate-500">{c.display_order}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => startEdit(c)} className="text-indigo-600 hover:underline text-xs mr-3">
                      Edit
                    </button>
                    <button onClick={() => deleteCat(c.id)} className="text-rose-600 hover:underline text-xs">
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
