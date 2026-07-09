"use client";
import { useEffect, useState } from "react";
import { admin, ApiError } from "@/lib/api";
import type {
  PaymentProviderOut, PaymentProviderCreate, PaymentMode,
  PaymentProviderType,
} from "@/types/api";

interface FormState {
  id?: number;
  name: string;
  /** provider_type can't be changed on edit (would require a different
   *  provider class instance + different schema). New-row picker only. */
  provider_type: PaymentProviderType;
  mode: PaymentMode;
  display_name: string;
  public_key: string;
  api_secret: string;
  /** Razorpay: shared HMAC webhook signing secret.
   *  PayPal:   not used (PayPal uses cert-based verification via the
   *            verify-webhook-signature API; webhook_id goes below). */
  webhook_secret: string;
  /** PayPal only — webhook_id from the developer dashboard. Stored
   *  in config.webhook_id and used by the backend when forwarding
   *  inbound events to PayPal's verify endpoint. */
  paypal_webhook_id: string;
  /** PayPal only — what the buyer sees FIRST on PayPal's hosted page.
   *  Stored in config.landing_page. GUEST_CHECKOUT = card form first
   *  (guest pay-by-card, no PayPal account needed); LOGIN = PayPal
   *  login wall first; NO_PREFERENCE = PayPal decides. */
  paypal_landing_page: string;
  is_enabled: boolean;
}

const blank: FormState = {
  name: "", provider_type: "razorpay", mode: "test", display_name: "",
  public_key: "", api_secret: "", webhook_secret: "",
  paypal_webhook_id: "", paypal_landing_page: "GUEST_CHECKOUT",
  is_enabled: true,
};

/** Modal state for the per-row webhook-signature diagnostic. Holds the
 *  pasted body + signature, the row id under test, and the current
 *  result (null = haven't tested yet this session). */
interface WebhookTestState {
  providerId: number;
  body: string;
  signature: string;
  busy: boolean;
  result: { ok: boolean; reason: string; secret_configured: boolean } | null;
}


export default function PaymentProvidersPage() {
  const [rows, setRows] = useState<PaymentProviderOut[] | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<number, string>>({});
  const [whTest, setWhTest] = useState<WebhookTestState | null>(null);

  async function reload() {
    try { setRows(await admin.paymentProviders.list()); }
    catch (e) { setErr((e as ApiError).body.message); }
  }
  useEffect(() => { reload(); }, []);

  async function activate(id: number) {
    try { await admin.paymentProviders.activate(id); await reload(); }
    catch (e) { setErr((e as ApiError).body.message); }
  }

  async function runWebhookTest() {
    if (!whTest) return;
    setWhTest({ ...whTest, busy: true, result: null });
    try {
      const r = await admin.paymentProviders.testWebhookSignature(
        whTest.providerId,
        { payload: whTest.body, signature: whTest.signature });
      setWhTest({ ...whTest, busy: false, result: r });
    } catch (e) {
      setWhTest({
        ...whTest, busy: false,
        result: { ok: false, secret_configured: false,
                  reason: (e as ApiError).body?.message ?? String(e) },
      });
    }
  }
  /** Make this provider the non-INR-rail provider (typically PayPal).
   *  Razorpay stays on the INR rail independently. */
  async function activateNonInr(id: number) {
    try { await admin.paymentProviders.activateNonInr(id); await reload(); }
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
      // PayPal stores webhook_id inside config (not as a top-level
      // secret) because PayPal's webhook auth is cert-based, not HMAC.
      // landing_page rides along in the same config JSON — the backend
      // provider reads it at order-create time (guest card checkout).
      const config = form.provider_type === "paypal"
        ? { webhook_id: form.paypal_webhook_id.trim(),
            landing_page: form.paypal_landing_page }
        : undefined;

      if (form.id) {
        const payload: Record<string, unknown> = {
          name: form.name, mode: form.mode,
          display_name: form.display_name || null,
          public_key: form.public_key || null,
          is_enabled: form.is_enabled,
        };
        // Only send secrets if filled (otherwise keep existing).
        if (form.api_secret) payload.api_secret = form.api_secret;
        if (form.provider_type === "razorpay" && form.webhook_secret) {
          payload.webhook_secret = form.webhook_secret;
        }
        if (config) payload.config = config;
        await admin.paymentProviders.update(form.id, payload);
      } else {
        const payload: PaymentProviderCreate = {
          name: form.name, provider_type: form.provider_type, mode: form.mode,
          display_name: form.display_name || null,
          public_key: form.public_key,
          api_secret: form.api_secret,
          webhook_secret: (form.provider_type === "razorpay"
            ? form.webhook_secret || null
            : null),
          config: config ?? null,
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
      id: p.id, name: p.name,
      provider_type: p.provider_type,
      mode: p.mode as PaymentMode,
      display_name: p.display_name ?? "",
      public_key: p.public_key ?? "",
      api_secret: "",                // keep existing unless user types new
      webhook_secret: "",
      paypal_webhook_id: ((p.config?.webhook_id as string) ?? ""),
      paypal_landing_page: ((p.config?.landing_page as string)
                            ?? "GUEST_CHECKOUT"),
      is_enabled: p.is_enabled,
    });
  }

  return (
    <div className="p-8 max-w-5xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Payment Providers</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Two rails coexist: Razorpay for INR (the historical flow,
            unchanged), and PayPal for non-INR currencies. Activate
            one of each — credentials are stored encrypted; switch keys
            or modes (test ↔ live) without redeploying.
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
            {form.id
              ? `Edit ${form.provider_type} provider`
              : `New ${form.provider_type} provider`}
          </h2>
          <div className="grid sm:grid-cols-2 gap-4">
            {/* Type picker only on new — switching type on existing
                rows would orphan credentials shaped for the old type. */}
            {!form.id && (
              <Field label="Provider type">
                <select value={form.provider_type}
                        onChange={(e) => setForm({
                          ...form,
                          provider_type: e.target.value as PaymentProviderType,
                        })}
                        className={input}>
                  <option value="razorpay">Razorpay (INR rail)</option>
                  <option value="paypal">PayPal (non-INR rail)</option>
                </select>
              </Field>
            )}
            <Field label="Display name">
              <input value={form.name}
                     onChange={(e) => setForm({ ...form, name: e.target.value })}
                     placeholder={form.provider_type === "razorpay"
                       ? "Razorpay (Live)" : "PayPal (Live)"}
                     className={input} />
            </Field>
            <Field label="Mode">
              <select value={form.mode}
                      onChange={(e) => setForm({ ...form, mode: e.target.value as PaymentMode })}
                      className={input}>
                <option value="test">{form.provider_type === "paypal"
                  ? "test (sandbox)" : "test"}</option>
                <option value="live">live</option>
              </select>
            </Field>
            <Field label={form.provider_type === "paypal"
                  ? "Public key (PayPal Client ID)"
                  : "Public key (Razorpay key_id)"} full>
              <input value={form.public_key}
                     onChange={(e) => setForm({ ...form, public_key: e.target.value })}
                     placeholder={form.provider_type === "paypal"
                       ? "AcDe...XYZ (developer.paypal.com app)"
                       : "rzp_test_xxxxxxxxxxxx or rzp_live_xxxxxxxxxxxx"}
                     className={input} />
            </Field>
            <Field label={form.provider_type === "paypal"
                  ? `API secret (PayPal Client Secret)${form.id ? " — leave blank to keep" : ""}`
                  : `API secret (key_secret)${form.id ? " — leave blank to keep" : ""}`} full>
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
            {form.provider_type === "razorpay" ? (
              <Field label={`Webhook secret${form.id ? " — leave blank to keep" : ""}`} full>
                <input type="password" autoComplete="new-password"
                       value={form.webhook_secret}
                       onChange={(e) => setForm({ ...form, webhook_secret: e.target.value })}
                       placeholder="whsec_••••••••"
                       className={input} />
                <p className="text-xs text-slate-500 mt-1">
                  Shared HMAC-SHA256 signing secret from Razorpay dashboard.
                </p>
              </Field>
            ) : (
              <Field label="PayPal Webhook ID (optional)" full>
                <input value={form.paypal_webhook_id}
                       onChange={(e) => setForm({
                         ...form, paypal_webhook_id: e.target.value })}
                       placeholder="WH-XXXXXXXXXX..."
                       className={input} />
                <p className="text-xs text-slate-500 mt-1">
                  Not a secret — this is the <strong>identifier</strong> of
                  a webhook you register at{" "}
                  <a href="https://developer.paypal.com" target="_blank"
                      rel="noreferrer"
                      className="text-indigo-600 hover:underline">
                    developer.paypal.com
                  </a>{" "}
                  → Apps &amp; Credentials → Webhooks. PayPal signs
                  events with a certificate (no shared secret); we send
                  the ID + headers back to PayPal&apos;s
                  verify-webhook-signature API to authenticate inbound
                  deliveries.
                  <br /><br />
                  <strong>OK to leave blank for testing</strong> — the
                  buyer-side flow still works (frontend captures the
                  order directly after PayPal approval). The only thing
                  you lose is auto-activation on dropped browser tabs.
                  Add the ID later once a webhook is registered.
                </p>
              </Field>
            )}
            {form.provider_type === "paypal" && (
              <Field label="Checkout landing page (guest card payments)" full>
                <select value={form.paypal_landing_page}
                        onChange={(e) => setForm({
                          ...form, paypal_landing_page: e.target.value })}
                        className={input}>
                  <option value="GUEST_CHECKOUT">
                    Card form first — guests pay by card without a PayPal
                    account (recommended)
                  </option>
                  <option value="NO_PREFERENCE">
                    Let PayPal decide per buyer
                  </option>
                  <option value="LOGIN">
                    PayPal login first (previous behaviour)
                  </option>
                </select>
                <p className="text-xs text-slate-500 mt-1">
                  Controls what overseas buyers see first on PayPal&apos;s
                  payment page. &quot;Card form first&quot; keeps the
                  &quot;Log in to PayPal&quot; option available, so
                  PayPal-account buyers are unaffected. Also make sure the
                  PayPal <strong>business account</strong> has Account
                  Settings → Website payments → &quot;PayPal account
                  optional&quot; = <strong>On</strong>, or PayPal forces
                  account creation regardless of this setting.
                </p>
              </Field>
            )}
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
              (p.is_active || p.is_non_inr_active)
                ? "border-indigo-300 ring-2 ring-indigo-100"
                : "border-slate-200"
            }`}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-slate-900">{p.name}</span>
                    <Badge>{p.provider_type}</Badge>
                    <Badge>{p.mode}</Badge>
                    {p.is_active && <Badge color="indigo">● INR rail</Badge>}
                    {p.is_non_inr_active && (
                      <Badge color="indigo">● Non-INR rail</Badge>
                    )}
                    {!p.is_enabled && <Badge>disabled</Badge>}
                  </div>
                  <div className="text-xs text-slate-500 mt-2 space-y-0.5">
                    <div>Public key: <code className="bg-slate-100 px-1.5 py-0.5 rounded">{p.public_key ?? "—"}</code></div>
                    <div>API secret: {p.has_api_secret
                      ? <span className="text-emerald-700">✓ configured (encrypted)</span>
                      : <span className="text-rose-700">✗ missing</span>}</div>
                    {p.provider_type === "razorpay" ? (
                      <div>Webhook secret: {p.has_webhook_secret
                        ? <span className="text-emerald-700">✓ configured (encrypted)</span>
                        : <span className="text-slate-500">— not set</span>}</div>
                    ) : (
                      <div>Webhook ID: {p.config?.webhook_id
                        ? <code className="bg-slate-100 px-1.5 py-0.5 rounded">{String(p.config.webhook_id)}</code>
                        : <span className="text-amber-700">— not set (OK; webhooks unverified, in-browser capture flow still works)</span>}</div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {testResult[p.id] && (
                    <span className="text-xs text-slate-600">{testResult[p.id]}</span>
                  )}
                  <button onClick={() => test(p.id)}
                          className="text-xs text-slate-600 hover:text-indigo-700">Test</button>
                  {/* Razorpay-only webhook-signature diagnostic. PayPal
                      uses cert-based verification and doesn't have a
                      shared-secret to mismatch. */}
                  {p.provider_type === "razorpay" && (
                    <button onClick={() => setWhTest({
                      providerId: p.id, body: "", signature: "",
                      busy: false, result: null,
                    })}
                            title="Diagnose 'invalid webhook signature' errors"
                            className="text-xs text-slate-600 hover:text-indigo-700">
                      Test webhook
                    </button>
                  )}
                  {/* INR activation: only meaningful for Razorpay providers. */}
                  {p.provider_type === "razorpay" && !p.is_active && p.is_enabled && (
                    <button onClick={() => activate(p.id)}
                            className="text-xs text-emerald-600 hover:text-emerald-700 font-medium">
                      Activate (INR)
                    </button>
                  )}
                  {/* Non-INR activation: PayPal in the common case;
                      Razorpay could also be set as non-INR if the
                      account has international cards approval. */}
                  {!p.is_non_inr_active && p.is_enabled && (
                    <button onClick={() => activateNonInr(p.id)}
                            className="text-xs text-emerald-600 hover:text-emerald-700 font-medium">
                      Activate (Non-INR)
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

      {/* Webhook-signature diagnostic modal. Lives at the page root so
          the dimmed backdrop covers the row list. Paste a real
          delivery from Razorpay dashboard → "Recent deliveries" tab. */}
      {whTest && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-center
                        justify-center p-4"
             onClick={() => setWhTest(null)}>
          <div className="bg-white rounded-xl max-w-2xl w-full p-6 space-y-4
                          max-h-[90vh] overflow-y-auto"
               onClick={(e) => e.stopPropagation()}>
            <div>
              <h2 className="font-semibold text-slate-900">
                Test webhook signature
              </h2>
              <p className="text-xs text-slate-500 mt-1">
                Razorpay auto-disables a webhook that keeps 400-ing. To
                find out WHY it&apos;s rejecting, copy one of the recent
                failed deliveries from Razorpay Dashboard → Webhooks →
                your webhook → <strong>Recent Deliveries</strong> → click
                a row → copy the <code>Payload</code> (full JSON body) and
                the <code>x-razorpay-signature</code> header value. Paste
                both below. We&apos;ll run them through our verifier with
                the secret currently stored in this provider row and tell
                you whether they match.
              </p>
            </div>

            <Field label="Event body (paste the full JSON)" full>
              <textarea
                value={whTest.body}
                onChange={(e) => setWhTest({ ...whTest, body: e.target.value })}
                rows={8}
                placeholder={"{\"entity\":\"event\",\"event\":\"payment.captured\",...}"}
                className={`${input} font-mono text-xs`}
              />
            </Field>
            <Field label="x-razorpay-signature header" full>
              <input
                value={whTest.signature}
                onChange={(e) => setWhTest({ ...whTest, signature: e.target.value })}
                placeholder="64-char hex string"
                className={`${input} font-mono text-xs`}
              />
            </Field>

            {whTest.result && (
              <div className={`p-3 rounded-lg text-sm border ${
                whTest.result.ok
                  ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                  : "bg-rose-50 border-rose-200 text-rose-800"}`}>
                <div className="font-medium">
                  {whTest.result.ok
                    ? "✓ Signature would be accepted"
                    : "✗ Signature does NOT match"}
                </div>
                <div className="text-xs mt-1 leading-relaxed">
                  {whTest.result.reason}
                </div>
                {!whTest.result.secret_configured && (
                  <div className="text-xs mt-2 italic">
                    No webhook secret saved on this provider row.
                  </div>
                )}
              </div>
            )}

            <div className="flex items-center gap-3 pt-2 border-t border-slate-100">
              <button
                onClick={runWebhookTest}
                disabled={whTest.busy || !whTest.body.trim() || !whTest.signature.trim()}
                className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium
                           rounded-lg hover:bg-indigo-700 disabled:opacity-50">
                {whTest.busy ? "Testing…" : "Run verify"}
              </button>
              <button
                onClick={() => setWhTest(null)}
                className="px-4 py-2 bg-white text-slate-700 text-sm font-medium
                           border border-slate-300 rounded-lg hover:bg-slate-50">
                Close
              </button>
            </div>
          </div>
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
