"use client";
import { useEffect, useMemo, useState } from "react";
import { admin, ApiError } from "@/lib/api";
import { SecretInput } from "@/components/admin/SecretInput";
import type { SettingOut } from "@/types/api";


/** Display-priority order for settings groups. Anything not listed here
 *  falls through to the bottom in alphabetical order. Curated for
 *  operator workflow — the things you edit most often (content,
 *  assistant behavior) sit at the top; provider/infra plumbing sits
 *  below.
 *
 *  Future-proof: when the agentic toggle ships and adds
 *  `assistant.agentic.*` keys, they land in the existing "assistant"
 *  group automatically (grouping is by first dot-segment). No update
 *  needed here. */
const GROUP_ORDER: readonly string[] = [
  "site",        // brand/footer/header copy
  "landing",     // landing-page hero + lead capture
  "email",       // transactional email (lead → auto-offer SMTP)
  "exams",       // /exams banners
  "assistant",   // assistant behavior + handler prompts
  "chat",        // daily caps + cooldowns
  "pricing",     // GST / FX / supported currencies
  "payment",     // active providers (INR + non-INR)
  "llm",         // chat LLM provider id + cache TTL
  "embeddings",  // RAG embedding provider id + cache TTL
  "rag",         // top-k + similarity threshold
  "pmi",         // pmi.org link-out URLs
  "auth",        // auth-related knobs
  "geoip",       // GeoIP MaxMind config
];

/** Pretty labels for groups; falls back to capitalised key if not listed. */
const GROUP_LABEL: Record<string, string> = {
  site:       "Site chrome",
  landing:    "Landing page",
  email:      "Email (auto-offer)",
  exams:      "Exams page",
  assistant:  "AI assistant",
  chat:       "Chat limits",
  pricing:    "Pricing & FX",
  payment:    "Payment providers",
  llm:        "LLM provider",
  embeddings: "Embedding provider",
  rag:        "RAG retrieval",
  pmi:        "PMI links",
  auth:       "Authentication",
  geoip:      "GeoIP",
};


export default function SettingsPage() {
  const [rows, setRows] = useState<SettingOut[] | null>(null);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  async function reload() {
    try { setRows(await admin.settings.list()); }
    catch (e) { setErr((e as ApiError).body.message); }
  }
  useEffect(() => { reload(); }, []);

  // Group rows by first dot-segment ("assistant.foo.bar" → "assistant").
  // Sort each group by key alphabetically for stable visual order.
  // Re-runs when `rows` changes; cheap O(n log n) on ~60 keys.
  const groups = useMemo(() => {
    if (!rows) return null;
    const map = new Map<string, SettingOut[]>();
    for (const r of rows) {
      const prefix = r.key.split(".", 1)[0];
      if (!map.has(prefix)) map.set(prefix, []);
      map.get(prefix)!.push(r);
    }
    for (const arr of map.values()) {
      arr.sort((a, b) => a.key.localeCompare(b.key));
    }
    // Curated order first, then any unlisted prefixes alphabetically.
    const ordered: { name: string; rows: SettingOut[] }[] = [];
    for (const name of GROUP_ORDER) {
      if (map.has(name)) ordered.push({ name, rows: map.get(name)! });
    }
    const extras = [...map.keys()]
      .filter((k) => !GROUP_ORDER.includes(k))
      .sort();
    for (const name of extras) {
      ordered.push({ name, rows: map.get(name)! });
    }
    return ordered;
  }, [rows]);

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

  // Secret-setting save bypasses the JSON-parse step — license keys
  // can contain "=" / "/" / "+" which JSON.parse would reject. Always
  // send the raw string. The backend validator decides what's allowed.
  async function saveSecret(key: string, rawValue: string) {
    await admin.settings.update(key, rawValue);
    await reload();
  }

  return (
    <div className="p-8 max-w-4xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Runtime Settings</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Edits propagate within ~30 seconds. No restart required.
          Settings are grouped by area; click a section header to
          collapse it.
        </p>
      </header>
      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700
                              p-3 rounded-lg mb-4 text-sm">{err}</div>}
      {!groups ? <div className="text-slate-500">Loading…</div> : (
        <div className="space-y-4">
          {groups.map(({ name, rows }) => {
            const isCollapsed = collapsed[name] ?? false;
            const label = GROUP_LABEL[name] ?? name;
            return (
              <section key={name}
                        className="bg-white rounded-xl border border-slate-200
                                   overflow-hidden">
                <button
                  type="button"
                  onClick={() => setCollapsed(c => ({ ...c, [name]: !isCollapsed }))}
                  className="w-full px-4 py-3 bg-slate-50 border-b border-slate-200
                             flex items-center justify-between hover:bg-slate-100
                             transition-colors text-left"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-slate-400 font-mono">
                      {isCollapsed ? "▸" : "▾"}
                    </span>
                    <span className="font-semibold text-slate-900 text-sm">
                      {label}
                    </span>
                    <span className="text-xs text-slate-500">
                      {rows.length} {rows.length === 1 ? "setting" : "settings"}
                    </span>
                  </div>
                  <code className="text-xs text-slate-400 font-mono">{name}.*</code>
                </button>
                {!isCollapsed && (
                  <table className="w-full">
                    <tbody className="divide-y divide-slate-100">
                      {rows.map(r => {
                        const editing = r.key in edit;
                        // Secret rows render a write-only SecretInput.
                        // The server already sent the masked form in r.value.
                        if (r.is_secret) {
                          return (
                            <tr key={r.key}>
                              <td className="px-4 py-3 align-top w-[42%]">
                                <code className="text-sm font-mono text-slate-800">{r.key}</code>
                                {r.description && (
                                  <div className="text-xs text-slate-500 mt-0.5">{r.description}</div>
                                )}
                              </td>
                              <td className="px-4 py-3 align-top" colSpan={2}>
                                <SecretInput
                                  masked={typeof r.value === "string" ? r.value : ""}
                                  onSave={(v) => saveSecret(r.key, v)}
                                />
                              </td>
                            </tr>
                          );
                        }
                        const display = JSON.stringify(r.value);
                        return (
                          <tr key={r.key}>
                            <td className="px-4 py-3 align-top w-[42%]">
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
                            <td className="px-4 py-3 align-top w-[88px]">
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
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
