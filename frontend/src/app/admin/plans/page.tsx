"use client";
import { useEffect, useMemo, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type {
  PlanAdminOut, PlanCreate, BundleType, ExamSetSummaryOut,
  CourseOut,
} from "@/types/api";

interface FormState {
  id?: number;
  name: string;
  slug: string;
  description: string;
  bundle_type: BundleType;
  base_price_paise: number;
  discount_price_paise: number | null;
  duration_days: number;
  is_active: boolean;
  display_order: number;
  exam_set_ids: number[];
  course_ids: number[];
  perks_json: string;     // user-edited text → parsed on save
}

const blank: FormState = {
  name: "", slug: "", description: "", bundle_type: "exam_bundle",
  base_price_paise: 99900, discount_price_paise: null,
  duration_days: 365, is_active: true, display_order: 100,
  exam_set_ids: [], course_ids: [], perks_json: "{}",
};

function rupees(paise: number) { return (paise / 100).toFixed(2); }

export default function AdminPlansPage() {
  const [rows, setRows] = useState<PlanAdminOut[] | null>(null);
  const [examSets, setExamSets] = useState<ExamSetSummaryOut[]>([]);
  const [courses, setCourses] = useState<CourseOut[]>([]);
  const [editing, setEditing] = useState<PlanAdminOut | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function reload() {
    try {
      const [list, sets, cs] = await Promise.all([
        admin.plans.list(),
        admin.examSets.list(),
        // Courses are LMS-side — the plan admin needs them to populate
        // the multi-select. We pull both published + draft so admins
        // can bundle work-in-progress courses too.
        admin.lms.listCourses(true),
      ]);
      setRows(list); setExamSets(sets); setCourses(cs);
    } catch (e) { setErr(errMsg(e)); }
  }
  useEffect(() => { reload(); }, []);

  function startNew() {
    setEditing(null);
    setForm({ ...blank });
  }
  function startEdit(p: PlanAdminOut) {
    setEditing(p);
    setForm({
      id: p.id, name: p.name, slug: p.slug,
      description: p.description ?? "",
      bundle_type: p.bundle_type as BundleType,
      base_price_paise: p.base_price_paise,
      discount_price_paise: p.discount_price_paise,
      duration_days: p.duration_days,
      is_active: p.is_active, display_order: p.display_order,
      exam_set_ids: p.exam_sets.map(es => es.id),
      course_ids: (p.courses ?? []).map(c => c.id),
      perks_json: JSON.stringify(p.perks ?? {}, null, 2),
    });
  }
  function cancel() { setEditing(null); setForm(null); }

  async function save() {
    if (!form) return;
    setBusy(true); setErr(null);
    let perks: Record<string, unknown>;
    try { perks = JSON.parse(form.perks_json || "{}"); }
    catch { setErr("Perks must be valid JSON"); setBusy(false); return; }

    const payload: PlanCreate = {
      name: form.name, slug: form.slug,
      description: form.description || null,
      bundle_type: form.bundle_type,
      base_price_paise: form.base_price_paise,
      discount_price_paise: form.discount_price_paise ?? null,
      duration_days: form.duration_days,
      is_active: form.is_active,
      display_order: form.display_order,
      perks,
      exam_set_ids: form.exam_set_ids,
      course_ids: form.course_ids,
    };
    try {
      if (editing) {
        // Update — strip slug (backend does not update slug).
        const { slug: _slug, ...update } = payload;
        await admin.plans.update(editing.id, update);
      } else {
        await admin.plans.create(payload);
      }
      cancel(); await reload();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function remove(p: PlanAdminOut) {
    if (!confirm(`Delete plan "${p.name}"? (Use deactivate if it has payments.)`)) return;
    try { await admin.plans.delete(p.id); await reload(); }
    catch (e) { setErr(errMsg(e)); }
  }

  const examSetMap = useMemo(
    () => Object.fromEntries(examSets.map(es => [es.id, es])),
    [examSets]);

  return (
    <div className="p-8 max-w-5xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Pricing Plans</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Sellable bundles. Tag <strong>exam sets</strong> and/or <strong>courses</strong> to
            unlock on purchase — combine them in a single plan (e.g. ₹5000 = 3 exam sets + 2 courses).
            One-time order; access auto-expires after <code>duration_days</code>.
          </p>
        </div>
        {!form && (
          <button onClick={startNew}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
            + New Plan
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
            {editing ? `Edit plan #${editing.id}` : "New plan"}
          </h2>

          <div className="grid md:grid-cols-2 gap-4">
            <Field label="Name">
              <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                     className="w-full border border-slate-300 rounded px-3 py-2" />
            </Field>
            <Field label="Slug (URL-safe)">
              <input value={form.slug} disabled={!!editing}
                     onChange={e => setForm({ ...form, slug: e.target.value })}
                     className="w-full border border-slate-300 rounded px-3 py-2 disabled:bg-slate-100" />
            </Field>
            <Field label="Bundle type">
              <select value={form.bundle_type}
                      onChange={e => setForm({ ...form, bundle_type: e.target.value as BundleType })}
                      className="w-full border border-slate-300 rounded px-3 py-2">
                <option value="exam_bundle">Exam bundle</option>
                <option value="course_bundle">Course bundle</option>
                <option value="custom">Custom</option>
              </select>
            </Field>
            <Field label="Duration (days)">
              <input type="number" min={1} value={form.duration_days}
                     onChange={e => setForm({ ...form, duration_days: Number(e.target.value) })}
                     className="w-full border border-slate-300 rounded px-3 py-2" />
            </Field>
            <Field label="Base price (paise)">
              <input type="number" min={100} value={form.base_price_paise}
                     onChange={e => setForm({ ...form, base_price_paise: Number(e.target.value) })}
                     className="w-full border border-slate-300 rounded px-3 py-2" />
              <div className="text-xs text-slate-500 mt-1">
                ₹{rupees(form.base_price_paise)}
              </div>
            </Field>
            <Field label="Discount price (paise, optional)">
              <input type="number" min={0}
                     value={form.discount_price_paise ?? ""}
                     placeholder="leave blank for no discount"
                     onChange={e => setForm({
                       ...form,
                       discount_price_paise: e.target.value === "" ? null : Number(e.target.value),
                     })}
                     className="w-full border border-slate-300 rounded px-3 py-2" />
              <div className="text-xs text-slate-500 mt-1">
                {form.discount_price_paise != null
                  ? `₹${rupees(form.discount_price_paise)}`
                  : "—"}
              </div>
            </Field>
            <Field label="Display order">
              <input type="number" value={form.display_order}
                     onChange={e => setForm({ ...form, display_order: Number(e.target.value) })}
                     className="w-full border border-slate-300 rounded px-3 py-2" />
            </Field>
            <Field label="Active?">
              <label className="flex items-center gap-2 mt-2">
                <input type="checkbox" checked={form.is_active}
                       onChange={e => setForm({ ...form, is_active: e.target.checked })} />
                <span>Visible on /pricing</span>
              </label>
            </Field>
          </div>

          <Field label="Description">
            <textarea value={form.description}
                      onChange={e => setForm({ ...form, description: e.target.value })}
                      rows={2}
                      className="w-full border border-slate-300 rounded px-3 py-2" />
          </Field>

          <Field label="Tagged exam sets (these unlock on purchase)">
            <div className="border border-slate-300 rounded p-3 max-h-48 overflow-auto space-y-1">
              {examSets.length === 0 ? (
                <div className="text-sm text-slate-500">No exam sets yet.</div>
              ) : examSets.map(es => (
                <label key={es.id} className="flex items-center gap-2 text-sm">
                  <input type="checkbox"
                         checked={form.exam_set_ids.includes(es.id)}
                         onChange={e => {
                           const set = new Set(form.exam_set_ids);
                           if (e.target.checked) set.add(es.id); else set.delete(es.id);
                           setForm({ ...form, exam_set_ids: [...set] });
                         }} />
                  <span>{es.name}</span>
                  <span className="text-xs text-slate-400">/{es.slug}</span>
                </label>
              ))}
            </div>
          </Field>

          <Field label="Bundled courses (these unlock for active subscribers)">
            <div className="border border-slate-300 rounded p-3 max-h-48 overflow-auto space-y-1">
              {courses.length === 0 ? (
                <div className="text-sm text-slate-500">
                  No courses yet. Create courses at <a href="/admin/courses" className="text-indigo-600 hover:underline">/admin/courses</a>.
                </div>
              ) : courses.map(c => (
                <label key={c.id} className="flex items-center gap-2 text-sm">
                  <input type="checkbox"
                         checked={form.course_ids.includes(c.id)}
                         onChange={e => {
                           const set = new Set(form.course_ids);
                           if (e.target.checked) set.add(c.id); else set.delete(c.id);
                           setForm({ ...form, course_ids: [...set] });
                         }} />
                  <span>{c.title}</span>
                  <span className="text-xs text-slate-400">/{c.slug}</span>
                  {!c.is_published && (
                    <span className="text-[10px] uppercase tracking-wide bg-slate-100 text-slate-600 px-1.5 rounded">
                      draft
                    </span>
                  )}
                </label>
              ))}
            </div>
            <p className="text-xs text-slate-500 mt-2">
              When a user purchases this plan and the subscription is active, every
              bundled course shows up as enrolled in their <code>/lms/me/enrollments</code> list.
              Combine with exam sets above for an exam + course bundle (e.g. one
              ₹5000 plan = 3 exam sets + 2 courses).
            </p>
          </Field>

          <Field label="Perks (JSON, e.g. course bundles use course_zoom_url)">
            <textarea value={form.perks_json}
                      onChange={e => setForm({ ...form, perks_json: e.target.value })}
                      rows={3}
                      className="w-full font-mono text-xs border border-slate-300 rounded px-3 py-2" />
          </Field>

          <div className="flex gap-2 mt-4">
            <button onClick={save} disabled={busy}
                    className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg disabled:opacity-50">
              {busy ? "Saving…" : (editing ? "Save changes" : "Create plan")}
            </button>
            <button onClick={cancel}
                    className="px-4 py-2 border border-slate-300 text-sm rounded-lg">
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-2">Name</th>
              <th className="text-left px-4 py-2">Type</th>
              <th className="text-right px-4 py-2">Price</th>
              <th className="text-left px-4 py-2">Exam sets</th>
              <th className="text-left px-4 py-2">Courses</th>
              <th className="text-left px-4 py-2">Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows === null ? (
              <tr><td colSpan={7} className="px-4 py-6 text-slate-500">Loading…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-6 text-slate-500">
                No plans yet. Create one to start selling.
              </td></tr>
            ) : rows.map(p => (
              <tr key={p.id} className="border-t border-slate-100">
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-900">{p.name}</div>
                  <div className="text-xs text-slate-500">/{p.slug}</div>
                </td>
                <td className="px-4 py-3 text-slate-600">{p.bundle_type}</td>
                <td className="px-4 py-3 text-right">
                  {p.discount_price_paise != null ? (
                    <>
                      <span className="text-slate-400 line-through mr-1">
                        ₹{rupees(p.base_price_paise)}
                      </span>
                      <span className="font-semibold">₹{rupees(p.discount_price_paise)}</span>
                    </>
                  ) : (
                    <span className="font-semibold">₹{rupees(p.base_price_paise)}</span>
                  )}
                </td>
                <td className="px-4 py-3 text-slate-600">
                  {p.exam_sets.length === 0 ? "—"
                    : p.exam_sets.map(es => examSetMap[es.id]?.name ?? es.slug).join(", ")}
                </td>
                <td className="px-4 py-3 text-slate-600">
                  {(p.courses ?? []).length === 0 ? "—"
                    : p.courses.map(c => c.title).join(", ")}
                </td>
                <td className="px-4 py-3">
                  {p.is_active
                    ? <span className="text-emerald-700 text-xs bg-emerald-50 px-2 py-0.5 rounded">Active</span>
                    : <span className="text-slate-500 text-xs bg-slate-100 px-2 py-0.5 rounded">Hidden</span>}
                </td>
                <td className="px-4 py-3 text-right space-x-2">
                  <button onClick={() => startEdit(p)}
                          className="text-indigo-600 hover:underline text-sm">Edit</button>
                  <button onClick={() => remove(p)}
                          className="text-rose-600 hover:underline text-sm">Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block mb-3">
      <span className="block text-xs font-medium text-slate-700 mb-1">{label}</span>
      {children}
    </label>
  );
}
