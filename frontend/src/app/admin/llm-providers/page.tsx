"use client";
import { useEffect, useState } from "react";
import { admin, ApiError } from "@/lib/api";
import type {
  LLMProviderOut, LLMProviderCreate, ProviderType,
} from "@/types/api";

interface FormState {
  id?: number;
  name: string;
  provider_type: ProviderType;
  model: string;
  api_key: string;
  base_url: string;
  is_enabled: boolean;
}

const blank: FormState = {
  name: "", provider_type: "stub", model: "stub-v1",
  api_key: "", base_url: "", is_enabled: true,
};

export default function LLMProvidersPage() {
  const [rows, setRows] = useState<LLMProviderOut[] | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<number, string>>({});

  async function reload() {
    try { setRows(await admin.llmProviders.list()); }
    catch (e) { setErr((e as ApiError).body.message); }
  }
  useEffect(() => { reload(); }, []);

  async function activate(id: number) {
    try { await admin.llmProviders.activate(id); await reload(); }
    catch (e) { setErr((e as ApiError).body.message); }
  }
  async function test(id: number) {
    setTestResult(t => ({ ...t, [id]: "Testing…" }));
    try {
      const r = await admin.llmProviders.test(id);
      setTestResult(t => ({
        ...t, [id]: r.ok
          ? `✓ ${r.latency_ms ?? "?"}ms`
          : `✗ ${r.error ?? "Failed"}`,
      }));
    } catch (e) {
      setTestResult(t => ({ ...t, [id]: `✗ ${(e as ApiError).body.message}` }));
    }
  }
  async function remove(id: number) {
    if (!confirm("Delete provider?")) return;
    try { await admin.llmProviders.delete(id); await reload(); }
    catch (e) { setErr((e as ApiError).body.message); }
  }
  async function save() {
    if (!form) return;
    setBusy(true); setErr(null);
    try {
      if (form.id) {
        const payload: any = {
          name: form.name, model: form.model,
          base_url: form.base_url || null,
          is_enabled: form.is_enabled,
        };
        if (form.api_key) payload.api_key = form.api_key;
        await admin.llmProviders.update(form.id, payload);
      } else {
        const payload: LLMProviderCreate = {
          name: form.name, provider_type: form.provider_type, model: form.model,
          api_key: form.api_key || null,
          base_url: form.base_url || null,
          is_enabled: form.is_enabled,
        };
        await admin.llmProviders.create(payload);
      }
      setForm(null); await reload();
    } catch (e) { setErr((e as ApiError).body.message); }
    finally { setBusy(false); }
  }

  function startEdit(p: LLMProviderOut) {
    setForm({
      id: p.id, name: p.name,
      provider_type: p.provider_type as ProviderType,
      model: p.model,
      api_key: "", base_url: p.base_url ?? "",
      is_enabled: p.is_enabled,
    });
  }

  return (
    <div className="p-8 max-w-5xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">LLM Providers</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Add or rotate AI models. Active provider switches within ~30 seconds.
          </p>
        </div>
        {!form && (
          <button onClick={() => setForm({ ...blank })}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium
                             rounded-lg hover:bg-indigo-700">
            + Add Provider
          </button>
        )}
      </header>

      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700
                              p-3 rounded-lg mb-4 text-sm">{err}</div>}

      {form && (
        <div className="bg-white rounded-xl border-2 border-indigo-200 p-6 mb-6">
          <h2 className="font-semibold text-slate-900 mb-4">
            {form.id ? "Edit provider" : "New LLM provider"}
          </h2>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Name">
              <input value={form.name}
                     onChange={(e) => setForm({ ...form, name: e.target.value })}
                     placeholder="OpenAI GPT-4o" className={cls} />
            </Field>
            <Field label="Provider type">
              <select value={form.provider_type}
                      disabled={!!form.id}
                      onChange={(e) => setForm({ ...form,
                        provider_type: e.target.value as ProviderType })}
                      className={cls}>
                <option value="stub">stub (testing)</option>
                <option value="openai">openai</option>
                <option value="anthropic">anthropic</option>
                <option value="azure_openai">azure_openai</option>
                <option value="ollama">ollama</option>
              </select>
            </Field>
            <Field label="Model">
              <input value={form.model}
                     onChange={(e) => setForm({ ...form, model: e.target.value })}
                     placeholder="gpt-4o" className={cls} />
            </Field>
            <Field label="Base URL (optional)">
              <input value={form.base_url}
                     onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                     placeholder="https://api.openai.com/v1" className={cls} />
            </Field>
            <Field label={`API key${form.id ? " — leave blank to keep" : ""}`} full>
              <input type="password" autoComplete="new-password"
                     value={form.api_key}
                     onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                     placeholder="sk-…" className={cls} />
              <p className="text-xs text-slate-500 mt-1">
                Encrypted at rest with Fernet. Never returned in responses.
              </p>
            </Field>
          </div>
          <div className="flex items-center gap-3 mt-5">
            <button onClick={save} disabled={busy}
                    className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium
                               rounded-lg hover:bg-indigo-700 disabled:opacity-50">
              {busy ? "Saving…" : (form.id ? "Save changes" : "Add provider")}
            </button>
            <button onClick={() => setForm(null)}
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
           No LLM providers yet. Add one to enable AI chat.
         </div>
       ) : (
        <div className="space-y-3">
          {rows.map(p => (
            <div key={p.id} className={`bg-white rounded-xl border p-5 ${
              p.is_active ? "border-indigo-300 ring-2 ring-indigo-100" : "border-slate-200"
            }`}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-slate-900">{p.name}</span>
                    <SBadge>{p.provider_type}</SBadge>
                    <SBadge>{p.model}</SBadge>
                    {p.is_active && <SBadge color="indigo">● active</SBadge>}
                    {!p.is_enabled && <SBadge>disabled</SBadge>}
                  </div>
                  <div className="text-xs text-slate-500 mt-2 space-y-0.5">
                    {p.base_url && <div>Base URL: <code>{p.base_url}</code></div>}
                    <div>API key: {p.has_api_key
                      ? <span className="text-emerald-700">✓ configured (encrypted)</span>
                      : <span className="text-slate-500">— not required</span>}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {testResult[p.id] && (
                    <span className="text-xs text-slate-600">{testResult[p.id]}</span>
                  )}
                  <button onClick={() => test(p.id)}
                          className="text-xs text-slate-600 hover:text-indigo-700">Test</button>
                  {!p.is_active && p.is_enabled && (
                    <button onClick={() => activate(p.id)}
                            className="text-xs text-emerald-600 hover:text-emerald-700 font-medium">
                      Activate
                    </button>
                  )}
                  <button onClick={() => startEdit(p)}
                          className="text-xs text-slate-600 hover:text-slate-900">Edit</button>
                  <button onClick={() => remove(p.id)}
                          className="text-xs text-rose-600 hover:text-rose-700">Delete</button>
                </div>
              </div>
            </div>
          ))}
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
function SBadge({ children, color = "slate" }: { children: React.ReactNode; color?: string }) {
  const colors: Record<string, string> = {
    slate: "bg-slate-100 text-slate-700 border-slate-200",
    indigo: "bg-indigo-50 text-indigo-700 border-indigo-200",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${colors[color]}`}>
      {children}
    </span>
  );
}
