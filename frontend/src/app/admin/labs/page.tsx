"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { admin, content, errMsg } from "@/lib/api";
import type { LabAccessMode, LabIndexOut } from "@/types/api";

/**
 * Admin → Labs: one row per registered lab (backend
 * app/core/labs_registry.py). Edits the same Settings keys the raw
 * Runtime Settings screen exposes (labs.<key>_enabled / _title /
 * _access / _free_upto), with proper dropdowns so the cut point is
 * chosen by section title, not by id. Adding a lab to the registry
 * adds a row here with no UI change.
 */

const MODES: { value: LabAccessMode; label: string; help: string }[] = [
  { value: "free",    label: "Free",      help: "Everyone, full page. No login, no plan." },
  { value: "signin",  label: "Sign-in",   help: "Any logged-in account, full page. Plans are ignored." },
  { value: "preview", label: "Preview",   help: "Free up to the section below; the rest is blurred and locked unless the visitor's plan ticks this lab." },
  { value: "plan",    label: "Plan only", help: "Header only; the body is locked unless the visitor's plan ticks this lab." },
];

interface Row {
  enabled: boolean;
  title: string;
  mode: LabAccessMode;
  free_upto: string;
}

function rowOf(l: LabIndexOut): Row {
  return { enabled: l.enabled, title: l.title, mode: l.mode, free_upto: l.free_upto };
}

export default function AdminLabsPage() {
  const [labs, setLabs] = useState<LabIndexOut[] | null>(null);
  const [rows, setRows] = useState<Record<string, Row>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function reload() {
    try {
      const list = await content.labs();
      setLabs(list);
      const r: Record<string, Row> = {};
      for (const l of list) r[l.slug] = rowOf(l);
      setRows(r);
    } catch (e) { setErr(errMsg(e)); }
  }
  useEffect(() => { reload(); }, []);

  function set(slug: string, patch: Partial<Row>) {
    setRows(prev => ({ ...prev, [slug]: { ...prev[slug], ...patch } }));
  }

  async function save(l: LabIndexOut) {
    const r = rows[l.slug]; if (!r) return;
    setBusy(l.slug); setErr(null); setSaved(null);
    try {
      const writes: [string, unknown][] = [];
      if (r.enabled !== l.enabled) writes.push([`labs.${l.key}_enabled`, r.enabled]);
      if (r.title.trim() !== l.title) writes.push([`labs.${l.key}_title`, r.title.trim() || l.default_title]);
      if (l.gated) {
        if (r.mode !== l.mode) writes.push([`labs.${l.key}_access`, r.mode]);
        if (r.free_upto !== l.free_upto) writes.push([`labs.${l.key}_free_upto`, r.free_upto]);
      }
      for (const [k, v] of writes) await admin.settings.update(k, v);
      await reload();
      setSaved(l.slug);
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(null); }
  }

  return (
    <div className="p-8 max-w-5xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Labs &amp; Walkthroughs</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Who can open each lab, and where the free preview stops. Changes
          reach the public pages within about a minute. Which <b>plans</b>{" "}
          unlock a lab is ticked per plan under{" "}
          <Link href="/admin/plans" className="text-indigo-600 hover:underline">Plans</Link>.
        </p>
      </header>
      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">{err}</div>}
      {!labs ? <div className="text-slate-500">Loading…</div> : (
        <div className="space-y-4">
          {labs.map(l => {
            const r = rows[l.slug] ?? rowOf(l);
            const dirty = JSON.stringify(r) !== JSON.stringify(rowOf(l));
            const modeHelp = MODES.find(m => m.value === r.mode)?.help;
            return (
              <section key={l.slug} className="bg-white rounded-xl border border-slate-200 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
                  <div>
                    <div className="text-xs uppercase tracking-wide text-slate-500">
                      {l.group === "walkthrough" ? "Visual walkthrough" : "Interactive lab"} · /labs/{l.slug}
                    </div>
                    <div className="font-semibold text-slate-900">{l.default_title}</div>
                  </div>
                  <div className="flex items-center gap-3">
                    {l.plans.length > 0 && (
                      <span className="text-xs text-slate-500">
                        Ticked on: {l.plans.map(p => p.name).join(", ")}
                      </span>
                    )}
                    <a href={`/labs/${l.slug}`} target="_blank" rel="noopener"
                       className="text-xs text-indigo-600 hover:underline">Open ↗</a>
                  </div>
                </div>

                <div className="grid md:grid-cols-[auto_1fr] gap-x-6 gap-y-3 items-center text-sm">
                  <label className="font-medium text-slate-700">Shown on /labs</label>
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={r.enabled}
                           onChange={e => set(l.slug, { enabled: e.target.checked })} />
                    <span className="text-slate-600">Off hides the card and redirects the page to /labs</span>
                  </label>

                  <label className="font-medium text-slate-700">Display title</label>
                  <input value={r.title} maxLength={80}
                         onChange={e => set(l.slug, { title: e.target.value })}
                         className="border border-slate-300 rounded px-3 py-1.5 w-full max-w-lg" />

                  {l.gated ? (
                    <>
                      <label className="font-medium text-slate-700">Access</label>
                      <div>
                        <select value={r.mode}
                                onChange={e => set(l.slug, { mode: e.target.value as LabAccessMode })}
                                className="border border-slate-300 rounded px-3 py-1.5">
                          {MODES.filter(m => m.value !== "preview" || l.cuttable)
                                .map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                        </select>
                        <div className="text-xs text-slate-500 mt-1">{modeHelp}</div>
                      </div>
                      {l.cuttable && r.mode === "preview" && (
                        <>
                          <label className="font-medium text-slate-700">Free up to</label>
                          <div>
                            <select value={r.free_upto}
                                    onChange={e => set(l.slug, { free_upto: e.target.value })}
                                    className="border border-slate-300 rounded px-3 py-1.5 max-w-lg">
                              <option value="">— nothing free (header only) —</option>
                              {l.sections.map((s, i) => (
                                <option key={s.id} value={s.id}>
                                  {i + 1}. {s.title}{i === l.sections.length - 1 ? " (everything)" : ""}
                                </option>
                              ))}
                            </select>
                            <div className="text-xs text-slate-500 mt-1">
                              Visible through this section; the remaining{" "}
                              {Math.max(0, l.sections.length - (l.sections.findIndex(s => s.id === r.free_upto) + 1))}{" "}
                              are blurred and locked.
                            </div>
                          </div>
                        </>
                      )}
                    </>
                  ) : (
                    <>
                      <label className="font-medium text-slate-700">Access</label>
                      <div className="text-slate-500">Always free — this lab is a built-in interactive page, not an embedded document.</div>
                    </>
                  )}
                </div>

                <div className="flex items-center gap-3 mt-4">
                  <button onClick={() => save(l)} disabled={!dirty || busy === l.slug}
                          className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg disabled:opacity-50">
                    {busy === l.slug ? "Saving…" : "Save"}
                  </button>
                  {dirty && <button onClick={() => set(l.slug, rowOf(l))}
                                    className="text-sm text-slate-500 hover:underline">Discard</button>}
                  {saved === l.slug && !dirty && <span className="text-sm text-emerald-700">Saved</span>}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
