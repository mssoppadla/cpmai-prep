"use client";
/**
 * Email templates — the lead → auto-offer reply copy.
 *
 * Each template is selected by lead `source` (intent); the "Default
 * (fallback)" row (source = null) is used when no source-specific active
 * template matches. Body is raw HTML (inline styles for highlighted text
 * / font sizes). {{placeholders}} are filled at send time by the backend
 * mailer; the live preview substitutes sample values so the operator can
 * eyeball the result.
 *
 * SMTP credentials + the advertised offer code live in /admin/settings
 * (the `email.*` keys) — this page only manages the templates.
 */
import { useEffect, useMemo, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type {
  EmailTemplateOut, EmailTemplateCreate, EmailTemplateUpdate,
} from "@/types/api";

// Lead sources a template can target (mirrors backend LeadSource). The
// empty value maps to the default/fallback template (source = null).
const SOURCE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "",               label: "Default (fallback — any source)" },
  { value: "landing_hero",   label: "Landing hero form" },
  { value: "newsletter",     label: "Newsletter" },
  { value: "exit_intent",    label: "Exit intent" },
  { value: "gated_download", label: "Gated download" },
  { value: "blog",           label: "Blog" },
  { value: "pricing_page",   label: "Pricing page" },
  { value: "exam_preview",   label: "Exam preview" },
  { value: "demo_request",   label: "Demo request" },
  { value: "chat_callback",  label: "Chat callback" },
];

const PLACEHOLDERS = [
  "{{name}}", "{{email}}", "{{offer_code}}",
  "{{offer_valid_until}}", "{{enroll_url}}", "{{brand_name}}",
];

// Sample values used only for the in-page live preview.
const PREVIEW_CTX: Record<string, string> = {
  name: "Alex",
  email: "alex@example.com",
  offer_code: "WELCOME20",
  offer_valid_until: "17 Jun 2026, 09:00 UTC",
  enroll_url: "https://cpmaiexamprep.com/pricing",
  brand_name: "CPMAI Exam Prep",
};

function renderPreview(html: string): string {
  return html.replace(/\{\{\s*(\w+)\s*\}\}/g, (m, k) =>
    k in PREVIEW_CTX ? PREVIEW_CTX[k] : m);
}

interface FormState {
  source: string;       // "" = default
  subject: string;
  html_body: string;
  is_active: boolean;
}

const STARTER_BODY =
  `<div style="font-family: Arial, sans-serif; color: #1e293b; line-height: 1.6;">
  <p>Hi {{name}},</p>
  <p>Thanks for signing up for the free CPMAI mock exam! 🎉</p>
  <p>As a welcome, here's an exclusive offer to enroll in the full
     <strong>course + exam bundle</strong>:</p>
  <p style="font-size: 22px; font-weight: bold; color: #4f46e5;
            background: #eef2ff; padding: 12px 16px; border-radius: 8px;
            display: inline-block;">
     {{offer_code}}
  </p>
  <p style="color: #b91c1c;"><strong>Hurry — this code is active for 24 hours
     (until {{offer_valid_until}}).</strong></p>
  <p><a href="{{enroll_url}}"
        style="background: #4f46e5; color: #fff; padding: 12px 20px;
               border-radius: 8px; text-decoration: none; font-weight: bold;">
     Enroll now &rarr;</a></p>
  <p>See you inside,<br/>The {{brand_name}} team</p>
</div>`;

const blank: FormState = {
  source: "", subject: "Your CPMAI welcome offer (24 hours only) 🎁",
  html_body: STARTER_BODY, is_active: true,
};

export default function AdminEmailTemplatesPage() {
  const [rows, setRows] = useState<EmailTemplateOut[] | null>(null);
  const [editing, setEditing] = useState<EmailTemplateOut | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function reload() {
    try { setRows(await admin.emailTemplates.list()); }
    catch (e) { setErr(errMsg(e)); }
  }
  useEffect(() => { reload(); }, []);

  function startNew() { setEditing(null); setForm({ ...blank }); setNotice(null); }
  function startEdit(t: EmailTemplateOut) {
    setEditing(t);
    setForm({
      source: t.source ?? "",
      subject: t.subject,
      html_body: t.html_body,
      is_active: t.is_active,
    });
    setNotice(null);
  }
  function cancel() { setEditing(null); setForm(null); }

  async function save() {
    if (!form) return;
    setBusy(true); setErr(null);
    const payload: EmailTemplateCreate = {
      source: form.source || null,
      subject: form.subject,
      html_body: form.html_body,
      is_active: form.is_active,
    };
    try {
      if (editing) {
        const update: EmailTemplateUpdate = payload;
        await admin.emailTemplates.update(editing.id, update);
      } else {
        await admin.emailTemplates.create(payload);
      }
      await reload();
      cancel();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function remove(t: EmailTemplateOut) {
    if (!confirm(`Delete this template (${t.source ?? "default"})?`)) return;
    try { await admin.emailTemplates.delete(t.id); await reload(); }
    catch (e) { setErr(errMsg(e)); }
  }

  async function sendTest(t: EmailTemplateOut) {
    setNotice(null); setErr(null);
    const to = prompt(
      "Send a test render to which email? (blank = your own admin email)") ?? "";
    try {
      const r = await admin.emailTemplates.test(t.id, to.trim() || undefined);
      setNotice(r.sent
        ? `Test email sent to ${r.to}.`
        : `Could not send — check the email.* SMTP settings in Runtime Settings.`);
    } catch (e) { setErr(errMsg(e)); }
  }

  const previewHtml = useMemo(
    () => (form ? renderPreview(form.html_body) : ""), [form]);

  return (
    <div className="p-8 max-w-5xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Email templates</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Auto-reply sent to a lead on a consented sign-up. Configure SMTP
            credentials and the offer code under{" "}
            <a href="/admin/settings" className="text-indigo-600 hover:underline">
              Runtime Settings → email.*
            </a>, then flip <code className="text-xs">email.automation_enabled</code> on.
          </p>
        </div>
        {!form && (
          <button onClick={startNew}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium
                             rounded-lg hover:bg-indigo-700">
            New template
          </button>
        )}
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700
                                     p-3 rounded-lg mb-4 text-sm">{err}</div>
      )}
      {notice && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800
                        p-3 rounded-lg mb-4 text-sm">{notice}</div>
      )}

      {form ? (
        <div className="bg-white border border-slate-200 rounded-xl p-5 mb-6">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Intent (lead source)
              </label>
              <select
                value={form.source}
                onChange={(e) => setForm({ ...form, source: e.target.value })}
                className="w-full px-3 py-2 text-sm border border-slate-300 rounded"
              >
                {SOURCE_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={form.is_active}
                       onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
                Active (eligible to be sent)
              </label>
            </div>
          </div>

          <div className="mt-4">
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Subject
            </label>
            <input
              value={form.subject}
              onChange={(e) => setForm({ ...form, subject: e.target.value })}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded"
            />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                HTML body
              </label>
              <textarea
                value={form.html_body}
                rows={18}
                onChange={(e) => setForm({ ...form, html_body: e.target.value })}
                className="w-full px-3 py-2 text-xs font-mono border border-slate-300
                           rounded resize-y"
              />
              <p className="text-xs text-slate-500 mt-2">
                Placeholders:{" "}
                {PLACEHOLDERS.map(p => (
                  <code key={p} className="mr-1 px-1 bg-slate-100 rounded">{p}</code>
                ))}
              </p>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Live preview (sample values)
              </label>
              <div className="border border-slate-200 rounded p-4 bg-white
                              min-h-[18rem] overflow-auto"
                   dangerouslySetInnerHTML={{ __html: previewHtml }} />
            </div>
          </div>

          <div className="mt-5 flex gap-2">
            <button onClick={save} disabled={busy}
                    className="px-4 py-2 bg-indigo-600 text-white text-sm rounded
                               hover:bg-indigo-700 disabled:opacity-50">
              {busy ? "Saving…" : editing ? "Save changes" : "Create template"}
            </button>
            <button onClick={cancel}
                    className="px-4 py-2 bg-white text-slate-700 text-sm border
                               border-slate-300 rounded hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {!rows ? (
        <div className="text-slate-500">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center
                        text-slate-500">
          No email templates yet. Create a Default template so the automation has
          something to send.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase">
                <th className="px-4 py-3">Intent</th>
                <th className="px-4 py-3">Subject</th>
                <th className="px-4 py-3">Active</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(t => (
                <tr key={t.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-sm text-slate-700">
                    {t.source
                      ? <code className="text-xs">{t.source}</code>
                      : <span className="text-xs px-2 py-0.5 rounded bg-amber-50
                                         text-amber-700 border border-amber-200">
                          default
                        </span>}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-900">{t.subject}</td>
                  <td className="px-4 py-3 text-sm">
                    {t.is_active
                      ? <span className="text-emerald-700">✓ active</span>
                      : <span className="text-slate-400">inactive</span>}
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <button onClick={() => sendTest(t)}
                            className="text-xs text-slate-600 hover:underline mr-3">
                      Send test
                    </button>
                    <button onClick={() => startEdit(t)}
                            className="text-xs text-indigo-600 hover:underline mr-3">
                      Edit
                    </button>
                    <button onClick={() => remove(t)}
                            className="text-xs text-rose-600 hover:underline">
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
