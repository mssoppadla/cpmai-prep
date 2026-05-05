"use client";
import { useEffect, useState } from "react";
import { admin, ApiError } from "@/lib/api";
import type {
  PaymentProviderOut, PaymentProviderCreate, PaymentMode,
} from "@/types/api";

interface FormState {
  id?: number;
  name: string;
  mode: PaymentMode;
  display_name: string;
  public_key: string;
  api_secret: string;
  webhook_secret: string;
  is_enabled: boolean;
}

const blank: FormState = {
  name: "", mode: "test", display_name: "",
  public_key: "", api_secret: "", webhook_secret: "", is_enabled: true,
};

export default function PaymentProvidersPage() {
  const [rows, setRows] = useState<PaymentProviderOut[] | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<number, string>>({});

  async function reload() {
    try { setRows(await admin.paymentProviders.list()); }
    catch (e) { setErr((e as ApiError).body.message); }
  }
  useEffect(() => { reload(); }, []);

  async function activate(id: number) {
    try { await admin.paymentProviders.activate(id); await reload(); }
    catch (e) { setErr((e as ApiError).body.message); }
  }
  async function test(id: number) {
    setTestResult(t => ({ ...t, [id]: "Testing…" }));
    try {
      const r = await admin.paymentProviders.test(id);
      setTestResult(t => ({
        ...t, [id]: r.ok ? "✓ OK" : `✗ ${r.error ?? "Failed"}`,
      }));
    } catch (e) {
      setTestResult(t => ({ ...t, [id]: `✗ ${(e as ApiError).body.message}` }));
    }
  }
  async function remove(id: number) {
    if (!confirm("Delete this provider? This cannot be undone.")) return;
    try { await admin.paymentProviders.delete(id); await reload(); }
    catch (e) { setErr((e as ApiError).body.message); }
  }

  async function save() {
    if (!form) return;
    setBusy(true); setErr(null);
    try {
      if (form.id) {
        const payload: any = {
          name: form.name, mode: form.mode,
          display_name: form.display_name || null,
          public_key: form.public_key || null,
          is_enabled: form.is_enabled,
        };
        // Only send secrets if filled (otherwise keep existing)
        if (form.api_secret) payload.api_secret = form.api_secret;
        if (form.webhook_secret) payload.webhook_secret = form.webhook_secret;
        await admin.paymentProviders.update(form.id, payload);
      } else {
        const payload: PaymentProviderCreate = {
          name: form.name, provider_type: "razorpay", mode: form.mode,
          display_name: form.display_name || null,
          public_key: form.public_key,
          api_secret: form.api_secret,
          webhook_secret: form.webhook_secret || null,
          is_enabled: form.is_enabled,
        };
        await admin.paymentProviders.create(payload);
      }
      setForm(null);
      await reload();
    } catch (e) { setErr((e as ApiError).body.message); }
    finally { setBusy(false); }
  }

  function startEdit(p: PaymentProviderOut) {
    setForm({
      id: p.id, name: p.name, mode: p.mode as PaymentMode,
      display_name: p.display_name ?? "",
      public_key: p.public_key ?? "",
      api_secret: "",                // keep existing unless user types new
      webhook_secret: "",
      is_enabled: p.is_enabled,
    });
  }

  return (
    <div className="p-8 max-w-5xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Payment Providers</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Razorpay credentials are stored encrypted in the database.
            Switch keys or modes (test ↔ live) without redeploying.
          </p>
        </div>
        {!form && (
          <button onClick={() => setForm({ ...blank })}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium
                             rounded-lg hover:bg-indigo-700">
            + Add Razorpay Provider
          </button>
        )}
      </header>

      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700
                              p-3 rounded-lg mb-4 text-sm">{err}</div>}

      {form && (
        <div className="bg-white rounded-xl border-2 border-indigo-200 p-6 mb-6">
          <h2 className="font-semibold text-slate-900 mb-4">
            {form.id ? "Edit provider" : "New Razorpay provider"}
          </h2>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Display name">
              <input value={form.name}
                     onChange={(e) => setForm({ ...form, name: e.target.value })}
                     placeholder="Razorpay (Live)"
                     className={input} />
            </Field>
            <Field label="Mode">
              <select value={form.mode}
                      onChange={(e) => setForm({ ...form, mode: e.target.value as PaymentMode })}
                      className={input}>
                <option value="test">test</option>
                <option value="live">live</option>
              </select>
            </Field>
            <Field label="Public key (Razorpay key_id)" full>
              <input value={form.public_key}
                     onChange={(e) => setForm({ ...form, public_key: e.target.value })}
                     placeholder="rzp_test_xxxxxxxxxxxx or rzp_live_xxxxxxxxxxxx"
                     className={input} />
            </Field>
            <Field label={`API secret (key_secret)${form.id ? " — leave blank to keep" : ""}`} full>
              <input type="password" autoComplete="new-password"
                     value={form.api_secret}
                     onChange={(e) => setForm({ ...form, api_secret: e.target.value })}
                     placeholder="••••••••••••"
                     className={input} />
              <p className="text-xs text-slate-500 mt-1">
                Encrypted at rest with the platform ENCRYPTION_KEY (Fernet).
                Never returned in API responses.
              </p>
            </Field>
            <Field label={`Webhook secret${form.id ? " — leave blank to keep" : ""}`} full>
              <input type="password" autoComplete="new-password"
                     value={form.webhook_secret}
                     onChange={(e) => setForm({ ...form, webhook_secret: e.target.value })}
                     placeholder="whsec_••••••••"
                     className={input} />
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
         <div className="bg-white rounded-xl border border-slate-200 p-12 text-center">
           <div className="text-slate-700 font-medium">No payment providers yet</div>
           <div className="text-sm text-slate-500 mt-1">
             Add a Razorpay provider to enable payments.
           </div>
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
                    <Badge>{p.provider_type}</Badge>
                    <Badge>{p.mode}</Badge>
                    {p.is_active && <Badge color="indigo">● active</Badge>}
                    {!p.is_enabled && <Badge>disabled</Badge>}
                  </div>
                  <div className="text-xs text-slate-500 mt-2 space-y-0.5">
                    <div>Public key: <code className="bg-slate-100 px-1.5 py-0.5 rounded">{p.public_key ?? "—"}</code></div>
                    <div>API secret: {p.has_api_secret
                      ? <span className="text-emerald-700">✓ configured (encrypted)</span>
                      : <span className="text-rose-700">✗ missing</span>}</div>
                    <div>Webhook secret: {p.has_webhook_secret
                      ? <span className="text-emerald-700">✓ configured (encrypted)</span>
                      : <span className="text-slate-500">— not set</span>}</div>
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

const input = "w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none";

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

function Badge({ children, color = "slate" }: { children: React.ReactNode; color?: string }) {
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
