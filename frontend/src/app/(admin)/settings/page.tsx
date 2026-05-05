"use client";
import { useEffect, useState } from "react";
import { admin, ApiError } from "@/lib/api";
import type { SettingOut } from "@/types/api";

export default function SettingsPage() {
  const [rows, setRows] = useState<SettingOut[] | null>(null);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function reload() {
    try { setRows(await admin.settings.list()); }
    catch (e) { setErr((e as ApiError).body.message); }
  }
  useEffect(() => { reload(); }, []);

  async function save(key: string) {
    setBusy(key); setErr(null);
    let value: unknown = edit[key];
    try {
      // Try parsing as JSON first (so numbers, bools, null work)
      try { value = JSON.parse(edit[key]); } catch {}
      await admin.settings.update(key, value);
      await reload();
      setEdit(prev => { const n = { ...prev }; delete n[key]; return n; });
    } catch (e) { setErr((e as ApiError).body.message); }
    finally { setBusy(null); }
  }

  return (
    <div className="p-8 max-w-4xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Runtime Settings</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Edits propagate within ~30 seconds. No restart required.
        </p>
      </header>
      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700
                              p-3 rounded-lg mb-4 text-sm">{err}</div>}
      {!rows ? <div className="text-slate-500">Loading…</div> : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase">
                <th className="px-4 py-3">Key</th>
                <th className="px-4 py-3">Value</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(r => {
                const editing = r.key in edit;
                const display = JSON.stringify(r.value);
                return (
                  <tr key={r.key}>
                    <td className="px-4 py-3 align-top">
                      <code className="text-sm font-mono text-slate-800">{r.key}</code>
                      {r.description && (
                        <div className="text-xs text-slate-500 mt-0.5">{r.description}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <input
                        value={editing ? edit[r.key] : display}
                        onChange={(e) => setEdit(p => ({ ...p, [r.key]: e.target.value }))}
                        className="w-full px-3 py-1.5 text-sm font-mono border
                                   border-slate-300 rounded focus:ring-1
                                   focus:ring-indigo-500 outline-none"
                      />
                    </td>
                    <td className="px-4 py-3 align-top">
                      {editing && (
                        <button onClick={() => save(r.key)}
                                disabled={busy === r.key}
                                className="px-3 py-1.5 bg-indigo-600 text-white text-xs
                                           rounded hover:bg-indigo-700 disabled:opacity-50">
                          {busy === r.key ? "Saving…" : "Save"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
