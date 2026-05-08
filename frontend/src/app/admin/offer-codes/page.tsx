"use client";
import { useEffect, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type {
  OfferCodeAdminOut, OfferCodeCreate, DiscountType,
} from "@/types/api";

interface FormState {
  code: string;
  description: string;
  discount_type: DiscountType;
  discount_value: number;
  valid_from: string;       // datetime-local
  valid_until: string;
  max_redemptions: number | null;
  is_active: boolean;
}

const blank: FormState = {
  code: "", description: "",
  discount_type: "percent", discount_value: 10,
  valid_from: "", valid_until: "",
  max_redemptions: null, is_active: true,
};

function toIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
function toLocal(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  // Strip seconds/milliseconds — datetime-local inputs accept "YYYY-MM-DDTHH:mm".
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function AdminOfferCodesPage() {
  const [rows, setRows] = useState<OfferCodeAdminOut[] | null>(null);
  const [editing, setEditing] = useState<OfferCodeAdminOut | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function reload() {
    try { setRows(await admin.offerCodes.list()); }
    catch (e) { setErr(errMsg(e)); }
  }
  useEffect(() => { reload(); }, []);

  function startNew() { setEditing(null); setForm({ ...blank }); }
  function startEdit(c: OfferCodeAdminOut) {
    setEditing(c);
    setForm({
      code: c.code, description: c.description ?? "",
      discount_type: c.discount_type, discount_value: c.discount_value,
      valid_from: toLocal(c.valid_from),
      valid_until: toLocal(c.valid_until),
      max_redemptions: c.max_redemptions,
      is_active: c.is_active,
    });
  }
  function cancel() { setEditing(null); setForm(null); }

  async function save() {
    if (!form) return;
    setBusy(true); setErr(null);
    const payload: OfferCodeCreate = {
      code: form.code, description: form.description || null,
      discount_type: form.discount_type, discount_value: form.discount_value,
      valid_from: toIso(form.valid_from),
      valid_until: toIso(form.valid_until),
      max_redemptions: form.max_redemptions,
      is_active: form.is_active,
    };
    try {
      if (editing) {
        const { code: _code, ...update } = payload;
        await admin.offerCodes.update(editing.id, update);
      } else {
        await admin.offerCodes.create(payload);
      }
      cancel(); await reload();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function remove(c: OfferCodeAdminOut) {
    if (!confirm(`Delete code "${c.code}"? (Codes with redemptions can only be deactivated.)`)) return;
    try { await admin.offerCodes.delete(c.id); await reload(); }
    catch (e) { setErr(errMsg(e)); }
  }

  return (
    <div className="p-8 max-w-5xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Offer Codes</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Discount coupons. Global N-redemption. Whether they stack with
            plan discounts is controlled by{" "}
            <code className="text-xs">pricing.stack_offer_with_discount</code>{" "}
            in Runtime Settings.
          </p>
        </div>
        {!form && (
          <button onClick={startNew}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
            + New Offer
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
            {editing ? `Edit code ${editing.code}` : "New offer code"}
          </h2>

          <div className="grid md:grid-cols-2 gap-4">
            <Field label="Code (uppercased on save)">
              <input value={form.code} disabled={!!editing}
                     onChange={e => setForm({ ...form, code: e.target.value })}
                     className="w-full border border-slate-300 rounded px-3 py-2 disabled:bg-slate-100 uppercase" />
            </Field>
            <Field label="Description">
              <input value={form.description}
                     onChange={e => setForm({ ...form, description: e.target.value })}
                     className="w-full border border-slate-300 rounded px-3 py-2" />
            </Field>
            <Field label="Discount type">
              <select value={form.discount_type}
                      onChange={e => setForm({ ...form, discount_type: e.target.value as DiscountType })}
                      className="w-full border border-slate-300 rounded px-3 py-2">
                <option value="percent">Percent (0..100)</option>
                <option value="flat">Flat (paise)</option>
              </select>
            </Field>
            <Field label={`Discount value (${form.discount_type === "percent" ? "0..100" : "paise"})`}>
              <input type="number" min={0} value={form.discount_value}
                     onChange={e => setForm({ ...form, discount_value: Number(e.target.value) })}
                     className="w-full border border-slate-300 rounded px-3 py-2" />
            </Field>
            <Field label="Valid from (optional)">
              <input type="datetime-local" value={form.valid_from}
                     onChange={e => setForm({ ...form, valid_from: e.target.value })}
                     className="w-full border border-slate-300 rounded px-3 py-2" />
            </Field>
            <Field label="Valid until (optional)">
              <input type="datetime-local" value={form.valid_until}
                     onChange={e => setForm({ ...form, valid_until: e.target.value })}
                     className="w-full border border-slate-300 rounded px-3 py-2" />
            </Field>
            <Field label="Max redemptions (blank = unlimited)">
              <input type="number" min={1}
                     value={form.max_redemptions ?? ""}
                     onChange={e => setForm({
                       ...form,
                       max_redemptions: e.target.value === "" ? null : Number(e.target.value),
                     })}
                     className="w-full border border-slate-300 rounded px-3 py-2" />
            </Field>
            <Field label="Active?">
              <label className="flex items-center gap-2 mt-2">
                <input type="checkbox" checked={form.is_active}
                       onChange={e => setForm({ ...form, is_active: e.target.checked })} />
                <span>Accepts new redemptions</span>
              </label>
            </Field>
          </div>

          <div className="flex gap-2 mt-4">
            <button onClick={save} disabled={busy}
                    className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg disabled:opacity-50">
              {busy ? "Saving…" : (editing ? "Save changes" : "Create code")}
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
              <th className="text-left px-4 py-2">Code</th>
              <th className="text-left px-4 py-2">Discount</th>
              <th className="text-right px-4 py-2">Used / Max</th>
              <th className="text-left px-4 py-2">Window</th>
              <th className="text-left px-4 py-2">Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows === null ? (
              <tr><td colSpan={6} className="px-4 py-6 text-slate-500">Loading…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-6 text-slate-500">No offer codes yet.</td></tr>
            ) : rows.map(c => (
              <tr key={c.id} className="border-t border-slate-100">
                <td className="px-4 py-3 font-mono">{c.code}</td>
                <td className="px-4 py-3">
                  {c.discount_type === "percent"
                    ? `${c.discount_value}% off`
                    : `₹${(c.discount_value/100).toFixed(2)} off`}
                </td>
                <td className="px-4 py-3 text-right text-slate-600">
                  {c.used_count} / {c.max_redemptions ?? "∞"}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">
                  {c.valid_from ? new Date(c.valid_from).toLocaleDateString() : "—"}
                  {" → "}
                  {c.valid_until ? new Date(c.valid_until).toLocaleDateString() : "—"}
                </td>
                <td className="px-4 py-3">
                  {c.is_active
                    ? <span className="text-emerald-700 text-xs bg-emerald-50 px-2 py-0.5 rounded">Active</span>
                    : <span className="text-slate-500 text-xs bg-slate-100 px-2 py-0.5 rounded">Off</span>}
                </td>
                <td className="px-4 py-3 text-right space-x-2">
                  <button onClick={() => startEdit(c)}
                          className="text-indigo-600 hover:underline text-sm">Edit</button>
                  <button onClick={() => remove(c)}
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
