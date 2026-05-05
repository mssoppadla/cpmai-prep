"use client";
import { useEffect, useState } from "react";
import { admin, ApiError } from "@/lib/api";
import type { LeadAdminOut, LeadSource } from "@/types/api";

const SOURCES: Array<{ value: string; label: string }> = [
  { value: "",                label: "All sources" },
  { value: "landing_hero",    label: "Landing hero" },
  { value: "newsletter",      label: "Newsletter" },
  { value: "exit_intent",     label: "Exit intent" },
  { value: "gated_download",  label: "Gated download" },
  { value: "blog",            label: "Blog" },
  { value: "pricing_page",    label: "Pricing" },
  { value: "exam_preview",    label: "Exam preview" },
  { value: "demo_request",    label: "Demo request" },
];

export default function LeadsPage() {
  const [rows, setRows] = useState<LeadAdminOut[] | null>(null);
  const [filter, setFilter] = useState({ source: "", q: "" });
  const [editing, setEditing] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function reload() {
    try {
      const params: any = { limit: 200 };
      if (filter.source) params.source = filter.source;
      if (filter.q)      params.q = filter.q;
      setRows(await admin.leads.list(params));
    } catch (e) { setErr((e as ApiError).body.message); }
  }
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, []);

  async function saveNotes(id: number) {
    try {
      await admin.leads.updateNotes(id, notes);
      setEditing(null); setNotes("");
      await reload();
    } catch (e) { setErr((e as ApiError).body.message); }
  }

  async function exportCsv() {
    const params: Record<string, string> = {};
    if (filter.source) params.source = filter.source;
    if (filter.q)      params.q = filter.q;
    const qs = new URLSearchParams(params).toString();
    const url = `${process.env.NEXT_PUBLIC_API_URL}/admin/leads/export.csv${qs ? "?" + qs : ""}`;
    const token = typeof window !== "undefined"
      ? window.localStorage.getItem("cpmai.access") : null;
    try {
      const r = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = `leads-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(objUrl);
    } catch (e) {
      setErr(`Export failed: ${(e as Error).message}`);
    }
  }

  return (
    <div className="p-8 max-w-6xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Leads</h1>
          <p className="text-slate-600 mt-1 text-sm">
            All capture surfaces with UTM context. Stitched to anonymous journey
            via <code className="bg-slate-100 px-1 rounded text-xs">anon_id</code>.
          </p>
        </div>
        <button onClick={exportCsv}
                className="px-4 py-2 bg-white text-slate-700 text-sm font-medium
                           border border-slate-300 rounded-lg hover:bg-slate-50">
          Export CSV
        </button>
      </header>

      <div className="bg-white border border-slate-200 rounded-xl p-3 mb-4 flex gap-2">
        <input value={filter.q}
               onChange={(e) => setFilter({ ...filter, q: e.target.value })}
               placeholder="Search email…"
               className="flex-1 px-3 py-1.5 text-sm border border-slate-300 rounded" />
        <select value={filter.source}
                onChange={(e) => setFilter({ ...filter, source: e.target.value })}
                className="px-3 py-1.5 text-sm border border-slate-300 rounded">
          {SOURCES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <button onClick={reload}
                className="px-4 py-1.5 bg-slate-700 text-white text-sm rounded
                           hover:bg-slate-800">
          Filter
        </button>
      </div>

      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700
                              p-3 rounded-lg mb-4 text-sm">{err}</div>}
      {!rows ? <div className="text-slate-500">Loading…</div>
       : rows.length === 0 ? (
         <div className="bg-white rounded-xl border border-slate-200 p-12 text-center
                         text-slate-500">
           No leads match the filter.
         </div>
       ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase">
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">UTM</th>
                <th className="px-4 py-3">Target exam</th>
                <th className="px-4 py-3">Consent</th>
                <th className="px-4 py-3">Captured</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(l => (
                <>
                  <tr key={l.id} className="hover:bg-slate-50 cursor-pointer"
                      onClick={() => {
                        setEditing(editing === l.id ? null : l.id);
                        setNotes(l.notes ?? "");
                      }}>
                    <td className="px-4 py-3">
                      <div className="text-sm font-medium text-slate-900">{l.email}</div>
                      {l.name && <div className="text-xs text-slate-500">{l.name}</div>}
                      {l.converted_user_id && (
                        <span className="text-xs text-emerald-700 font-medium">
                          ✓ converted
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-600">{l.source}</td>
                    <td className="px-4 py-3 text-xs text-slate-600">
                      {l.utm_source && (
                        <div>{l.utm_source}{l.utm_medium ? ` / ${l.utm_medium}` : ""}</div>
                      )}
                      {l.utm_campaign && (
                        <div className="text-slate-500">{l.utm_campaign}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-600">
                      {l.target_exam_date ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {l.consent_marketing
                        ? <span className="text-emerald-700">✓ yes</span>
                        : <span className="text-slate-500">no</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">
                      {new Date(l.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                  {editing === l.id && (
                    <tr className="bg-slate-50">
                      <td colSpan={6} className="px-4 py-4">
                        <div className="text-xs font-semibold text-slate-700 mb-2">
                          Internal notes (admin-only)
                        </div>
                        <textarea value={notes} rows={3}
                                  onChange={(e) => setNotes(e.target.value)}
                                  placeholder="Sales follow-up, qualifying details…"
                                  className="w-full px-3 py-2 text-sm border
                                             border-slate-300 rounded mb-2" />
                        <div className="flex gap-2">
                          <button onClick={() => saveNotes(l.id)}
                                  className="px-3 py-1.5 bg-indigo-600 text-white text-xs
                                             rounded hover:bg-indigo-700">
                            Save notes
                          </button>
                          <button onClick={() => { setEditing(null); setNotes(""); }}
                                  className="px-3 py-1.5 bg-white text-slate-700 text-xs
                                             border border-slate-300 rounded
                                             hover:bg-slate-50">
                            Cancel
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
