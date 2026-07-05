"use client";
/**
 * Email Automations — admin-extensible lifecycle mail types.
 * Contract: docs/contracts/email-automation.md
 *
 * Three tabs:
 *   1. Email Account — SMTP setup for contact@cpmaiexamprep.com with an
 *      inline Hostinger guide, config-completeness banner, and a REAL
 *      test-send that surfaces the actual SMTP error (R8).
 *   2. Mail Types — the automations list + editor: trigger picker (with
 *      per-trigger placeholder cheat-sheet), condition builder, delay
 *      in d/h/m, live-preview HTML body, attachments, send policy,
 *      per-type active toggle (R2..R6).
 *   3. Activity — the outbox: every queued/sent/skipped/failed mail per
 *      user with dates + reasons, so the admin always knows whether a
 *      mail went out (R7).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type {
  EmailAutomationCatalog, EmailAutomationCreate, EmailAutomationOut,
  EmailAttachment, EmailCondition, EmailOutboxRow,
} from "@/types/api";

/* ────────────────────────────────────────────────────── shared bits ── */

const PREVIEW_CTX: Record<string, string> = {
  name: "Alex", email: "alex@example.com", offer_code: "WELCOME20",
  offer_valid_until: "17 Jun 2026, 09:00 UTC",
  enroll_url: "https://cpmaiexamprep.com/pricing",
  brand_name: "CPMAI Exam Prep", signup_method: "google",
  plan_name: "CPMAI Full Prep", amount: "4999.00", currency: "INR",
  expires_at: "31 Dec 2026", provider: "razorpay", hours_since: "3",
  exam_title: "CPMAI Mock Exam 2", score: "82", passed: "passed",
  attempt_date: "03 Jul 2026",
};

function renderPreview(html: string): string {
  return html.replace(/\{\{\s*(\w+)\s*\}\}/g, (m, k) =>
    k in PREVIEW_CTX ? PREVIEW_CTX[k] : m);
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function fmtDelay(minutes: number): string {
  const d = Math.floor(minutes / 1440);
  const h = Math.floor((minutes % 1440) / 60);
  const m = minutes % 60;
  const parts: string[] = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  if (m || parts.length === 0) parts.push(`${m}m`);
  return parts.join(" ");
}

const STATUS_STYLE: Record<string, string> = {
  pending:   "bg-amber-50 text-amber-700 border-amber-200",
  sent:      "bg-emerald-50 text-emerald-700 border-emerald-200",
  skipped:   "bg-slate-100 text-slate-600 border-slate-200",
  failed:    "bg-rose-50 text-rose-700 border-rose-200",
  cancelled: "bg-slate-100 text-slate-500 border-slate-200",
};

/* ─────────────────────────────────────────────────────── main page ── */

type Tab = "account" | "types" | "activity";

export default function AdminEmailAutomationsPage() {
  const [tab, setTab] = useState<Tab>("types");
  const [catalog, setCatalog] = useState<EmailAutomationCatalog | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    admin.emailAutomations.catalog()
      .then(setCatalog)
      .catch((e) => setErr(errMsg(e)));
  }, []);

  return (
    <div className="p-8 max-w-6xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Email Automations</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Lifecycle mail types sent from your configured mailbox — each one
          personalized per user, with its own trigger, timing, conditions and
          attachments. Add new mail types any time; no code change needed.
        </p>
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200
                                     text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      <nav className="flex gap-1 border-b border-slate-200 mb-6">
        {([
          ["account", "1. Email Account"],
          ["types", "2. Mail Types"],
          ["activity", "3. Activity"],
        ] as Array<[Tab, string]>).map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
                  className={`px-4 py-2 text-sm font-medium rounded-t-lg border
                              border-b-0 ${tab === key
                                ? "bg-white border-slate-200 text-indigo-700"
                                : "bg-slate-50 border-transparent text-slate-500 hover:text-slate-700"}`}>
            {label}
          </button>
        ))}
      </nav>

      {tab === "account" && <EmailAccountTab masterOn={catalog?.master_switch_on ?? false} />}
      {tab === "types" && catalog && <MailTypesTab catalog={catalog} />}
      {tab === "types" && !catalog && <div className="text-slate-500">Loading…</div>}
      {tab === "activity" && <ActivityTab />}
    </div>
  );
}

/* ──────────────────────────────────────────── tab 1: Email Account ── */

const SMTP_KEYS = [
  "email.from_address", "email.from_name", "email.smtp_host",
  "email.smtp_port", "email.smtp_use_ssl", "email.smtp_username",
  "email.smtp_password", "email.lifecycle_enabled",
] as const;

function EmailAccountTab({ masterOn }: { masterOn: boolean }) {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [loaded, setLoaded] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [testBusy, setTestBusy] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);

  useEffect(() => {
    admin.settings.list().then((rows) => {
      const v: Record<string, unknown> = {};
      for (const r of rows) {
        if ((SMTP_KEYS as readonly string[]).includes(r.key)) v[r.key] = r.value;
      }
      setValues(v);
      setLoaded(true);
    }).catch((e) => setErr(errMsg(e)));
  }, []);

  // "password saved" shows as ••••last4 from the masked GET — treat any
  // non-empty value as configured.
  const missing = useMemo(() => {
    const req: Array<[string, string]> = [
      ["email.from_address", "From address"],
      ["email.smtp_host", "SMTP host"],
      ["email.smtp_username", "Username"],
      ["email.smtp_password", "Password"],
    ];
    return req.filter(([k]) => !String(values[k] ?? "").trim())
              .map(([, label]) => label);
  }, [values]);

  async function saveKey(key: string, value: unknown) {
    setBusyKey(key); setErr(null); setNotice(null);
    try {
      const r = await admin.settings.update(key, value);
      setValues((v) => ({ ...v, [key]: r.value }));
      setNotice(`Saved ${key}.`);
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusyKey(null); }
  }

  async function runSmtpTest() {
    setTestBusy(true); setErr(null); setNotice(null);
    try {
      const r = await admin.emailAutomations.smtpTest();
      if (r.ok) setNotice(`✓ Test email sent to ${r.to} — SMTP works.`);
      else setErr(`SMTP test failed: ${r.error}`);
    } catch (e) { setErr(errMsg(e)); }
    finally { setTestBusy(false); }
  }

  function prefillHostinger() {
    saveKey("email.smtp_host", "smtp.hostinger.com");
    saveKey("email.smtp_port", 465);
    saveKey("email.smtp_use_ssl", true);
  }

  if (!loaded) return <div className="text-slate-500">Loading…</div>;

  const enabled = values["email.lifecycle_enabled"] === true;

  return (
    <div className="space-y-5">
      {/* status banner */}
      {missing.length > 0 ? (
        <div className="bg-amber-50 border border-amber-200 text-amber-800
                        p-3 rounded-lg text-sm">
          <b>Not fully configured.</b> Missing: {missing.join(", ")}. Emails
          cannot be sent until these are set.
        </div>
      ) : (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800
                        p-3 rounded-lg text-sm">
          ✓ Email account configured{enabled || masterOn
            ? " — automations master switch is ON."
            : ". Flip the master switch below to start sending."}
        </div>
      )}
      {err && <div role="alert" className="bg-rose-50 border border-rose-200
                                           text-rose-700 p-3 rounded-lg text-sm">{err}</div>}
      {notice && <div className="bg-emerald-50 border border-emerald-200
                                 text-emerald-800 p-3 rounded-lg text-sm">{notice}</div>}

      <div className="bg-white border border-slate-200 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-slate-900">
            Mailbox credentials (contact@cpmaiexamprep.com)
          </h2>
          <button onClick={prefillHostinger}
                  className="text-xs text-indigo-600 hover:underline">
            Prefill Hostinger defaults
          </button>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {([
            ["email.from_address", "From address", "contact@cpmaiexamprep.com", "text"],
            ["email.from_name", "From name", "CPMAI Exam Prep", "text"],
            ["email.smtp_host", "SMTP host", "smtp.hostinger.com", "text"],
            ["email.smtp_port", "SMTP port", "465", "number"],
            ["email.smtp_username", "Username (full email)", "contact@cpmaiexamprep.com", "text"],
            ["email.smtp_password", "Password", "mailbox password", "password"],
          ] as Array<[string, string, string, string]>).map(([key, label, ph, type]) => (
            <SettingField key={key} k={key} label={label} placeholder={ph}
                          type={type} value={values[key]}
                          busy={busyKey === key} onSave={saveKey} />
          ))}
        </div>
        <div className="mt-4 flex items-center gap-6">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox"
                   checked={values["email.smtp_use_ssl"] === true}
                   onChange={(e) => saveKey("email.smtp_use_ssl", e.target.checked)} />
            Use SSL (port 465). Untick for STARTTLS (port 587).
          </label>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-slate-900 mb-2">Verify &amp; enable</h2>
        <div className="flex flex-wrap items-center gap-4">
          <button onClick={runSmtpTest} disabled={testBusy}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm rounded
                             hover:bg-indigo-700 disabled:opacity-50">
            {testBusy ? "Testing…" : "Send test email to me"}
          </button>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={enabled}
                   disabled={missing.length > 0 && !enabled}
                   onChange={(e) => saveKey("email.lifecycle_enabled", e.target.checked)} />
            <b>Master switch</b> — automations send only while this is ON.
            {missing.length > 0 && !enabled && (
              <span className="text-xs text-amber-700">(complete the config first)</span>
            )}
          </label>
        </div>
        <p className="text-xs text-slate-500 mt-2">
          While the master switch is OFF, queued mails stay pending and go out
          when you switch it back on. Each mail type also has its own toggle
          in the Mail Types tab.
        </p>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-5">
        <button onClick={() => setGuideOpen(!guideOpen)}
                className="text-sm font-semibold text-slate-900 flex items-center gap-2">
          <span>{guideOpen ? "▾" : "▸"}</span> Setup guide — configuring
          contact@cpmaiexamprep.com (Hostinger)
        </button>
        {guideOpen && (
          <ol className="mt-4 space-y-3 text-sm text-slate-700 list-decimal ml-5">
            <li>
              <b>Create the mailbox.</b> Log in to Hostinger hPanel →
              <i> Emails</i> → domain <code>cpmaiexamprep.com</code> →
              <i> Create email account</i>. Name it
              <code className="mx-1">contact@cpmaiexamprep.com</code> and set a
              strong password (you&apos;ll paste it above).
            </li>
            <li>
              <b>Enter the credentials on this page.</b> Host
              <code className="mx-1">smtp.hostinger.com</code>, port
              <code className="mx-1">465</code> with SSL ticked (or port 587
              with SSL unticked). Username is the FULL email address; password
              is the mailbox password from step 1. Use the &quot;Prefill
              Hostinger defaults&quot; button to fill host/port/SSL.
            </li>
            <li>
              <b>Check deliverability DNS (SPF / DKIM / DMARC).</b> In hPanel →
              <i> Emails → cpmaiexamprep.com → Domain settings</i>, Hostinger
              shows the required DNS records and whether they are active. If the
              domain&apos;s DNS is hosted at Hostinger these are added
              automatically; if DNS is elsewhere, copy the shown
              <code className="mx-1">SPF</code> (TXT),
              <code className="mx-1">DKIM</code> (TXT) and optionally a
              <code className="mx-1">DMARC</code> record into your DNS provider.
              Without them, automated mail is likely to land in spam.
            </li>
            <li>
              <b>Verify.</b> Click &quot;Send test email to me&quot; above and
              check your inbox. The button reports the exact SMTP error if
              something is off (wrong password → authentication failed; wrong
              port/SSL combo → connection error).
            </li>
            <li>
              <b>Enable.</b> Review each mail type&apos;s content in the Mail
              Types tab, switch the ones you want ON, then flip the master
              switch. Watch the first sends land in the Activity tab.
            </li>
          </ol>
        )}
      </div>
    </div>
  );
}

function SettingField({ k, label, placeholder, type, value, busy, onSave }: {
  k: string; label: string; placeholder: string; type: string;
  value: unknown; busy: boolean;
  onSave: (key: string, value: unknown) => Promise<void>;
}) {
  const [draft, setDraft] = useState(String(value ?? ""));
  const [dirty, setDirty] = useState(false);
  useEffect(() => { if (!dirty) setDraft(String(value ?? "")); },
            [value, dirty]);
  return (
    <div>
      <label className="block text-xs font-semibold text-slate-700 mb-1">
        {label}
      </label>
      <div className="flex gap-2">
        <input
          type={type === "password" ? "text" : type}
          value={draft}
          placeholder={placeholder}
          onChange={(e) => { setDraft(e.target.value); setDirty(true); }}
          className="flex-1 px-3 py-2 text-sm border border-slate-300 rounded"
        />
        {dirty && (
          <button
            onClick={async () => {
              await onSave(k, type === "number" ? Number(draft) : draft);
              setDirty(false);
            }}
            disabled={busy}
            className="px-3 py-2 text-xs bg-indigo-600 text-white rounded
                       hover:bg-indigo-700 disabled:opacity-50">
            {busy ? "…" : "Save"}
          </button>
        )}
      </div>
      {type === "password" && !dirty && String(value ?? "").startsWith("••••") && (
        <p className="text-xs text-slate-400 mt-1">
          Saved (masked — last 4 shown). Type a new value to replace.
        </p>
      )}
    </div>
  );
}

/* ───────────────────────────────────────────── tab 2: Mail Types ── */

interface FormState {
  name: string;
  trigger_key: string;
  conditions: EmailCondition[];
  delay_days: number; delay_hours: number; delay_mins: number;
  subject: string;
  html_body: string;
  attachments: EmailAttachment[];
  send_policy: string;
  cooldown_days: number;
  is_active: boolean;
}

function toForm(a?: EmailAutomationOut): FormState {
  const dm = a?.delay_minutes ?? 0;
  return {
    name: a?.name ?? "",
    trigger_key: a?.trigger_key ?? "user.signup",
    conditions: a?.conditions ?? [],
    delay_days: Math.floor(dm / 1440),
    delay_hours: Math.floor((dm % 1440) / 60),
    delay_mins: dm % 60,
    subject: a?.subject ?? "",
    html_body: a?.html_body ?? "<p>Hi {{name}},</p>\n<p></p>\n<p>— The {{brand_name}} team</p>",
    attachments: a?.attachments ?? [],
    send_policy: a?.send_policy ?? "once_per_user",
    cooldown_days: a?.cooldown_days ?? 0,
    is_active: a?.is_active ?? false,
  };
}

function fromForm(f: FormState): EmailAutomationCreate {
  return {
    name: f.name,
    trigger_key: f.trigger_key,
    conditions: f.conditions,
    delay_minutes: f.delay_days * 1440 + f.delay_hours * 60 + f.delay_mins,
    subject: f.subject,
    html_body: f.html_body,
    attachments: f.attachments,
    send_policy: f.send_policy as EmailAutomationCreate["send_policy"],
    cooldown_days: f.cooldown_days,
    is_active: f.is_active,
  };
}

function MailTypesTab({ catalog }: { catalog: EmailAutomationCatalog }) {
  const [rows, setRows] = useState<EmailAutomationOut[] | null>(null);
  const [editing, setEditing] = useState<EmailAutomationOut | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try { setRows(await admin.emailAutomations.list()); }
    catch (e) { setErr(errMsg(e)); }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  async function save() {
    if (!form) return;
    setBusy(true); setErr(null);
    try {
      if (editing) await admin.emailAutomations.update(editing.id, fromForm(form));
      else await admin.emailAutomations.create(fromForm(form));
      await reload();
      setEditing(null); setForm(null);
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function toggleActive(a: EmailAutomationOut) {
    setErr(null);
    try {
      await admin.emailAutomations.update(a.id, { is_active: !a.is_active });
      await reload();
    } catch (e) { setErr(errMsg(e)); }
  }

  async function remove(a: EmailAutomationOut) {
    if (!confirm(`Delete mail type "${a.name}"? Pending sends will be cancelled; history is kept.`)) return;
    try { await admin.emailAutomations.delete(a.id); await reload(); }
    catch (e) { setErr(errMsg(e)); }
  }

  async function sendTest(a: EmailAutomationOut) {
    setNotice(null); setErr(null);
    const to = prompt("Send a test render to which email? (blank = your admin email)") ?? "";
    try {
      const r = await admin.emailAutomations.test(a.id, to.trim() || undefined);
      setNotice(r.sent ? `Test email sent to ${r.to}.`
        : "Could not send — check the Email Account tab (SMTP settings).");
    } catch (e) { setErr(errMsg(e)); }
  }

  return (
    <div>
      {!catalog.master_switch_on && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800
                        p-3 rounded-lg mb-4 text-sm">
          The master switch is OFF — no automation sends anything yet. Configure
          and enable it in the Email Account tab.
        </div>
      )}
      {err && <div role="alert" className="bg-rose-50 border border-rose-200
                                           text-rose-700 p-3 rounded-lg mb-4 text-sm">{err}</div>}
      {notice && <div className="bg-emerald-50 border border-emerald-200
                                 text-emerald-800 p-3 rounded-lg mb-4 text-sm">{notice}</div>}

      {!form && (
        <div className="mb-4 text-right">
          <button onClick={() => { setEditing(null); setForm(toForm()); }}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm
                             font-medium rounded-lg hover:bg-indigo-700">
            New mail type
          </button>
        </div>
      )}

      {form && (
        <AutomationEditor
          form={form} setForm={setForm} catalog={catalog}
          busy={busy} isEdit={!!editing}
          onSave={save}
          onCancel={() => { setEditing(null); setForm(null); }}
        />
      )}

      {!rows ? (
        <div className="text-slate-500">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12
                        text-center text-slate-500">
          No mail types yet — create one above.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[52rem]">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase">
                <th className="px-4 py-3">Mail type</th>
                <th className="px-4 py-3">Trigger</th>
                <th className="px-4 py-3">Wait</th>
                <th className="px-4 py-3">Policy</th>
                <th className="px-4 py-3">Attach.</th>
                <th className="px-4 py-3">Enabled</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((a) => {
                const trig = catalog.triggers.find((t) => t.key === a.trigger_key);
                return (
                  <tr key={a.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 text-sm text-slate-900">{a.name}</td>
                    <td className="px-4 py-3 text-sm text-slate-700">
                      {trig?.label ?? <code className="text-xs">{a.trigger_key}</code>}
                      {a.conditions.length > 0 && (
                        <span className="ml-1 text-xs text-slate-400">
                          +{a.conditions.length} condition{a.conditions.length > 1 ? "s" : ""}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-700">{fmtDelay(a.delay_minutes)}</td>
                    <td className="px-4 py-3 text-xs text-slate-500">{a.send_policy.replace(/_/g, " ")}</td>
                    <td className="px-4 py-3 text-sm text-slate-700">
                      {a.attachments.length || "—"}
                    </td>
                    <td className="px-4 py-3">
                      {/* per-mail-type enable/disable (R6) */}
                      <button onClick={() => toggleActive(a)}
                              aria-label={`Toggle ${a.name}`}
                              className={`w-10 h-5 rounded-full relative transition
                                          ${a.is_active ? "bg-emerald-500" : "bg-slate-300"}`}>
                        <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full
                                          transition ${a.is_active ? "left-5" : "left-0.5"}`} />
                      </button>
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <button onClick={() => sendTest(a)}
                              className="text-xs text-slate-600 hover:underline mr-3">
                        Send test
                      </button>
                      <button onClick={() => { setEditing(a); setForm(toForm(a)); window.scrollTo(0, 0); }}
                              className="text-xs text-indigo-600 hover:underline mr-3">
                        Edit
                      </button>
                      <button onClick={() => remove(a)}
                              className="text-xs text-rose-600 hover:underline">
                        Delete
                      </button>
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

function AutomationEditor({ form, setForm, catalog, busy, isEdit, onSave, onCancel }: {
  form: FormState;
  setForm: (f: FormState) => void;
  catalog: EmailAutomationCatalog;
  busy: boolean; isEdit: boolean;
  onSave: () => void; onCancel: () => void;
}) {
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const trig = catalog.triggers.find((t) => t.key === form.trigger_key);
  const placeholders = [
    ...catalog.shared_placeholders, ...(trig?.placeholders ?? []),
  ].map((p) => `{{${p}}}`);
  const previewHtml = useMemo(() => renderPreview(form.html_body), [form.html_body]);
  const totalAttachBytes = form.attachments.reduce((s, a) => s + a.size_bytes, 0);

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploadBusy(true); setUploadErr(null);
    try {
      const r = await admin.uploads.file(file);
      setForm({ ...form, attachments: [...form.attachments, r] });
    } catch (ex) { setUploadErr(errMsg(ex)); }
    finally { setUploadBusy(false); }
  }

  function setCondition(i: number, patch: Partial<EmailCondition>) {
    const next = form.conditions.slice();
    next[i] = { ...next[i], ...patch };
    setForm({ ...form, conditions: next });
  }

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 mb-6">
      <h2 className="text-sm font-semibold text-slate-900 mb-4">
        {isEdit ? "Edit mail type" : "New mail type"}
      </h2>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Name (admin label)</label>
          <input value={form.name}
                 onChange={(e) => setForm({ ...form, name: e.target.value })}
                 placeholder="e.g. Welcome — signup without payment"
                 className="w-full px-3 py-2 text-sm border border-slate-300 rounded" />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Trigger (WHEN)</label>
          <select value={form.trigger_key}
                  onChange={(e) => setForm({ ...form, trigger_key: e.target.value })}
                  className="w-full px-3 py-2 text-sm border border-slate-300 rounded">
            {catalog.triggers.map((t) => (
              <option key={t.key} value={t.key}>{t.label}</option>
            ))}
          </select>
          {trig && <p className="text-xs text-slate-500 mt-1">{trig.description}</p>}
        </div>
      </div>

      {/* conditions builder */}
      <div className="mt-4">
        <label className="block text-xs font-semibold text-slate-700 mb-1">
          Conditions (IF — all must hold; re-checked at send time)
        </label>
        {form.conditions.map((c, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2 mb-2">
            <select value={c.type}
                    onChange={(e) => {
                      const next = form.conditions.slice();
                      next[i] = { type: e.target.value };
                      setForm({ ...form, conditions: next });
                    }}
                    className="px-2 py-1.5 text-sm border border-slate-300 rounded">
              {catalog.condition_types.map((ct) => (
                <option key={ct.type} value={ct.type}>{ct.label}</option>
              ))}
            </select>
            {c.type === "has_active_subscription" && (
              <select value={c.value === false ? "false" : "true"}
                      onChange={(e) => setCondition(i, { value: e.target.value === "true" })}
                      className="px-2 py-1.5 text-sm border border-slate-300 rounded">
                <option value="true">has paid</option>
                <option value="false">has NOT paid</option>
              </select>
            )}
            {c.type === "signup_method" && (
              <select value={String(c.value ?? "google")}
                      onChange={(e) => setCondition(i, { value: e.target.value })}
                      className="px-2 py-1.5 text-sm border border-slate-300 rounded">
                <option value="google">Google</option>
                <option value="password">Password</option>
              </select>
            )}
            {c.type === "exam_set_submitted" && (
              <>
                <select value={c.value === false ? "false" : "true"}
                        onChange={(e) => setCondition(i, { value: e.target.value === "true" })}
                        className="px-2 py-1.5 text-sm border border-slate-300 rounded">
                  <option value="true">HAS submitted</option>
                  <option value="false">has NOT submitted</option>
                </select>
                <select value={String(c.exam_set_id ?? "")}
                        onChange={(e) => setCondition(i, { exam_set_id: Number(e.target.value) })}
                        className="px-2 py-1.5 text-sm border border-slate-300 rounded">
                  <option value="" disabled>pick exam set…</option>
                  {catalog.exam_sets.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </>
            )}
            {c.type === "days_since_signup" && (
              <>
                <select value={String(c.op ?? "gt")}
                        onChange={(e) => setCondition(i, { op: e.target.value })}
                        className="px-2 py-1.5 text-sm border border-slate-300 rounded">
                  <option value="gt">more than</option>
                  <option value="lt">less than</option>
                </select>
                <input type="number" min={0} value={Number(c.days ?? 0)}
                       onChange={(e) => setCondition(i, { days: Number(e.target.value) })}
                       className="w-20 px-2 py-1.5 text-sm border border-slate-300 rounded" />
                <span className="text-sm text-slate-600">days ago</span>
              </>
            )}
            <button onClick={() => setForm({
                      ...form,
                      conditions: form.conditions.filter((_, j) => j !== i),
                    })}
                    className="text-xs text-rose-600 hover:underline">remove</button>
          </div>
        ))}
        <button onClick={() => setForm({
                  ...form,
                  conditions: [...form.conditions,
                               { type: "has_active_subscription", value: false }],
                })}
                className="text-xs text-indigo-600 hover:underline">
          + add condition
        </button>
      </div>

      {/* timing + policy */}
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            Wait before sending (WAIT)
          </label>
          <div className="flex items-center gap-1">
            {([["delay_days", "d"], ["delay_hours", "h"], ["delay_mins", "m"]] as
              Array<[keyof FormState, string]>).map(([k, unit]) => (
              <span key={k} className="flex items-center gap-1">
                <input type="number" min={0} value={Number(form[k])}
                       onChange={(e) => setForm({ ...form, [k]: Math.max(0, Number(e.target.value)) })}
                       className="w-16 px-2 py-1.5 text-sm border border-slate-300 rounded" />
                <span className="text-xs text-slate-500 mr-1">{unit}</span>
              </span>
            ))}
          </div>
          <p className="text-xs text-slate-500 mt-1">
            0 = send immediately. For &quot;Checkout abandoned&quot; this is
            also the abandonment threshold.
          </p>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">Send policy</label>
          <select value={form.send_policy}
                  onChange={(e) => setForm({ ...form, send_policy: e.target.value })}
                  className="w-full px-3 py-2 text-sm border border-slate-300 rounded">
            <option value="once_per_user">Once per user (never repeats)</option>
            <option value="replace_pending">Replace pending (latest event wins)</option>
            <option value="every_event">Every event</option>
          </select>
        </div>
        {form.send_policy === "every_event" && (
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Cooldown (days, 0 = none)
            </label>
            <input type="number" min={0} value={form.cooldown_days}
                   onChange={(e) => setForm({ ...form, cooldown_days: Math.max(0, Number(e.target.value)) })}
                   className="w-24 px-3 py-2 text-sm border border-slate-300 rounded" />
            <p className="text-xs text-slate-500 mt-1">
              Suppresses repeats within the window (spam protection).
            </p>
          </div>
        )}
      </div>

      {/* content */}
      <div className="mt-4">
        <label className="block text-xs font-semibold text-slate-700 mb-1">Subject</label>
        <input value={form.subject}
               onChange={(e) => setForm({ ...form, subject: e.target.value })}
               className="w-full px-3 py-2 text-sm border border-slate-300 rounded" />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">HTML body (SEND)</label>
          <textarea value={form.html_body} rows={14}
                    onChange={(e) => setForm({ ...form, html_body: e.target.value })}
                    className="w-full px-3 py-2 text-xs font-mono border
                               border-slate-300 rounded resize-y" />
          <p className="text-xs text-slate-500 mt-2">
            Placeholders for this trigger:{" "}
            {placeholders.map((p) => (
              <code key={p} className="mr-1 px-1 bg-slate-100 rounded">{p}</code>
            ))}
          </p>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            Live preview (sample values)
          </label>
          <div className="border border-slate-200 rounded p-4 bg-white
                          min-h-[14rem] overflow-auto"
               dangerouslySetInnerHTML={{ __html: previewHtml }} />
        </div>
      </div>

      {/* attachments */}
      <div className="mt-4">
        <label className="block text-xs font-semibold text-slate-700 mb-1">
          Attachments (PDFs, docs — sent with every mail of this type)
        </label>
        {form.attachments.map((a, i) => (
          <div key={i} className="flex items-center gap-3 text-sm text-slate-700 mb-1">
            <span>📎 {a.filename}</span>
            <span className="text-xs text-slate-400">
              {(a.size_bytes / (1024 * 1024)).toFixed(2)} MB
            </span>
            <button onClick={() => setForm({
                      ...form,
                      attachments: form.attachments.filter((_, j) => j !== i),
                    })}
                    className="text-xs text-rose-600 hover:underline">remove</button>
          </div>
        ))}
        <div className="flex items-center gap-3 mt-1">
          <label className="text-xs text-indigo-600 hover:underline cursor-pointer">
            {uploadBusy ? "Uploading…" : "+ upload attachment"}
            <input type="file" className="hidden" disabled={uploadBusy}
                   accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip,image/*"
                   onChange={onUpload} />
          </label>
          <span className={`text-xs ${totalAttachBytes > 15 * 1024 * 1024
                            ? "text-rose-600 font-semibold" : "text-slate-400"}`}>
            total {(totalAttachBytes / (1024 * 1024)).toFixed(2)} / 15 MB
          </span>
        </div>
        {uploadErr && <p className="text-xs text-rose-600 mt-1">{uploadErr}</p>}
      </div>

      <div className="mt-4 flex items-center gap-4">
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={form.is_active}
                 onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          Enabled (this mail type may send)
        </label>
      </div>

      <div className="mt-5 flex gap-2">
        <button onClick={onSave} disabled={busy || !form.name || !form.subject}
                className="px-4 py-2 bg-indigo-600 text-white text-sm rounded
                           hover:bg-indigo-700 disabled:opacity-50">
          {busy ? "Saving…" : isEdit ? "Save changes" : "Create mail type"}
        </button>
        <button onClick={onCancel}
                className="px-4 py-2 bg-white text-slate-700 text-sm border
                           border-slate-300 rounded hover:bg-slate-50">
          Cancel
        </button>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────── tab 3: Activity ── */

function ActivityTab() {
  const [page, setPage] = useState<{ total: number; items: EmailOutboxRow[] } | null>(null);
  const [status, setStatus] = useState("");
  const [email, setEmail] = useState("");
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const limit = 50;

  const reload = useCallback(async () => {
    try {
      setPage(await admin.emailAutomations.outbox({
        status: status || undefined,
        user_email: email.trim() || undefined,
        limit, offset,
      }));
    } catch (e) { setErr(errMsg(e)); }
  }, [status, email, offset]);
  useEffect(() => { reload(); }, [reload]);

  async function requeue(row: EmailOutboxRow) {
    setErr(null);
    try { await admin.emailAutomations.requeue(row.id); await reload(); }
    catch (e) { setErr(errMsg(e)); }
  }

  return (
    <div>
      {err && <div role="alert" className="bg-rose-50 border border-rose-200
                                           text-rose-700 p-3 rounded-lg mb-4 text-sm">{err}</div>}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <select value={status}
                onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
                className="px-3 py-2 text-sm border border-slate-300 rounded">
          <option value="">All statuses</option>
          {["pending", "sent", "skipped", "failed", "cancelled"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <input value={email} placeholder="filter by user email…"
               onChange={(e) => { setEmail(e.target.value); setOffset(0); }}
               className="px-3 py-2 text-sm border border-slate-300 rounded w-64" />
        <button onClick={reload}
                className="px-3 py-2 text-sm border border-slate-300 rounded
                           text-slate-600 hover:bg-slate-50">
          Refresh
        </button>
        {page && <span className="text-xs text-slate-500">{page.total} total</span>}
      </div>

      {!page ? (
        <div className="text-slate-500">Loading…</div>
      ) : page.items.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12
                        text-center text-slate-500">
          Nothing here yet — once automations fire (or you bulk-send), every
          mail shows up here with its status and date.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[56rem]">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase">
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Mail type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Scheduled</th>
                <th className="px-4 py-3">Sent</th>
                <th className="px-4 py-3">Detail</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {page.items.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50 align-top">
                  <td className="px-4 py-3 text-sm text-slate-900">
                    {r.user_email}
                    {r.source === "manual" && (
                      <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded
                                       bg-indigo-50 text-indigo-600 border
                                       border-indigo-200">manual</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-700">
                    {r.automation_name ?? <i className="text-slate-400">deleted type</i>}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded border
                                      ${STATUS_STYLE[r.status] ?? ""}`}>
                      {r.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600 whitespace-nowrap">
                    {fmtDate(r.scheduled_at)}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600 whitespace-nowrap">
                    {fmtDate(r.sent_at)}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 max-w-[16rem]">
                    {r.last_error ?? r.skip_reason ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {(r.status === "failed" || r.status === "skipped"
                      || r.status === "cancelled") && (
                      <button onClick={() => requeue(r)}
                              className="text-xs text-indigo-600 hover:underline">
                        Requeue
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {page && page.total > limit && (
        <div className="flex items-center gap-3 mt-4 text-sm">
          <button disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - limit))}
                  className="px-3 py-1.5 border border-slate-300 rounded
                             disabled:opacity-40">← Prev</button>
          <span className="text-slate-500">
            {offset + 1}–{Math.min(offset + limit, page.total)} of {page.total}
          </span>
          <button disabled={offset + limit >= page.total}
                  onClick={() => setOffset(offset + limit)}
                  className="px-3 py-1.5 border border-slate-300 rounded
                             disabled:opacity-40">Next →</button>
        </div>
      )}
    </div>
  );
}
