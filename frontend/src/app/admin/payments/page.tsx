"use client";
/**
 * Payments — success / failed / abandoned visibility for follow-up (R10).
 * Contract: docs/contracts/email-automation.md §8
 *
 * Read-only: follow-up happens either manually (contact the user) or via
 * the payment.failed / payment.abandoned mail types in
 * /admin/email-automations. "Abandoned" is a view over status=created
 * rows older than a threshold — we never mutate Payment.status for it
 * (the user can still complete an old order; webhooks must find the row
 * in its expected state).
 */
import { useCallback, useEffect, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type { PaymentAdminRow, PaymentsSummary } from "@/types/api";

const STATUS_STYLE: Record<string, string> = {
  captured: "bg-emerald-50 text-emerald-700 border-emerald-200",
  failed:   "bg-rose-50 text-rose-700 border-rose-200",
  created:  "bg-amber-50 text-amber-700 border-amber-200",
  refunded: "bg-slate-100 text-slate-600 border-slate-200",
};

type Filter =
  | { kind: "all" }
  | { kind: "status"; status: string }
  | { kind: "abandoned" };

export default function AdminPaymentsPage() {
  const [summary, setSummary] = useState<PaymentsSummary | null>(null);
  const [rows, setRows] = useState<PaymentAdminRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<Filter>({ kind: "all" });
  const [email, setEmail] = useState("");
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [busyInvoice, setBusyInvoice] = useState<number | null>(null);
  const limit = 50;

  useEffect(() => {
    admin.payments.summary().then(setSummary).catch((e) => setErr(errMsg(e)));
  }, []);

  const reload = useCallback(async () => {
    try {
      const p = await admin.payments.list({
        status: filter.kind === "status" ? filter.status : undefined,
        abandoned_hours: filter.kind === "abandoned" ? 24 : undefined,
        user_email: email.trim() || undefined,
        limit, offset,
      });
      setRows(p.items); setTotal(p.total);
    } catch (e) { setErr(errMsg(e)); }
  }, [filter, email, offset]);
  useEffect(() => { reload(); }, [reload]);

  async function downloadInvoice(p: PaymentAdminRow) {
    setBusyInvoice(p.id); setErr(null);
    try {
      const blob = await admin.payments.downloadInvoice(p.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${p.invoice_number ?? `invoice-${p.id}`}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusyInvoice(null); }
  }

  async function markPaid(p: PaymentAdminRow) {
    const ok = window.confirm(
      `Mark payment #${p.id} (${p.user_email}, ${p.currency} ` +
      `${(p.amount_paise / 100).toFixed(2)}) as PAID?\n\n` +
      `Use this when the money actually arrived at the gateway (e.g. a ` +
      `PayPal payment you accepted manually) but this row shows ` +
      `unpaid/failed. It grants the subscription and emails the ` +
      `invoice, exactly like a normal capture.`);
    if (!ok) return;
    setBusyInvoice(p.id); setErr(null);
    try {
      await admin.payments.markPaid(p.id);
      await reload();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusyInvoice(null); }
  }

  async function resendInvoice(p: PaymentAdminRow) {
    setBusyInvoice(p.id); setErr(null);
    try {
      const r = await admin.payments.sendInvoice(p.id);
      if (!r.sent) setErr("Invoice email failed to send — check SMTP settings.");
      await reload();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusyInvoice(null); }
  }

  function chip(label: string, count: number | undefined, f: Filter,
                active: boolean) {
    return (
      <button key={label}
              onClick={() => { setFilter(f); setOffset(0); }}
              className={`px-3 py-1.5 text-sm rounded-full border transition
                          ${active
                            ? "bg-indigo-600 text-white border-indigo-600"
                            : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"}`}>
        {label}{count !== undefined && (
          <span className="ml-1 text-xs opacity-75">({count})</span>
        )}
      </button>
    );
  }

  return (
    <div className="p-8 max-w-6xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Payments</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Every order with its outcome. <b>Failed</b> and <b>abandoned</b> rows
          are your follow-up leads — automate them with the
          &quot;Payment failed&quot; / &quot;Checkout abandoned&quot; mail types
          in <a href="/admin/email-automations"
                className="text-indigo-600 hover:underline">Email Automations</a>.
        </p>
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200
                                     text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 mb-4">
        {chip("All", undefined, { kind: "all" }, filter.kind === "all")}
        {chip("Captured", summary?.by_status?.captured,
              { kind: "status", status: "captured" },
              filter.kind === "status" && filter.status === "captured")}
        {chip("Failed", summary?.by_status?.failed,
              { kind: "status", status: "failed" },
              filter.kind === "status" && filter.status === "failed")}
        {chip("Abandoned >24h", summary?.abandoned_24h,
              { kind: "abandoned" }, filter.kind === "abandoned")}
        {chip("Refunded", summary?.by_status?.refunded,
              { kind: "status", status: "refunded" },
              filter.kind === "status" && filter.status === "refunded")}
        <input value={email} placeholder="filter by user email…"
               onChange={(e) => { setEmail(e.target.value); setOffset(0); }}
               className="ml-auto px-3 py-2 text-sm border border-slate-300
                          rounded w-64" />
      </div>

      {!rows ? (
        <div className="text-slate-500">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12
                        text-center text-slate-500">
          No payments match this filter.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[64rem]">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase">
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Plan</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Account</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Invoice</th>
                <th className="px-4 py-3">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-sm">
                    <div className="text-slate-900">{p.user_name ?? "—"}</div>
                    <div className="text-xs text-slate-500">{p.user_email}</div>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-700">
                    {p.plan_name ?? "—"}
                    {p.offer_code && (
                      <span className="ml-1 text-xs text-slate-400">
                        ({p.offer_code})
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-900">
                    {p.currency} {(p.amount_paise / 100).toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600">
                    {p.provider_account ?? p.provider_name}
                    <div className="text-[10px] text-slate-400">
                      {p.provider_order_id}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded border
                                      ${STATUS_STYLE[p.status] ?? ""}`}>
                      {p.status === "created" ? "unpaid (created)" : p.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {(p.status === "captured" || p.status === "refunded") ? (
                      <div className="flex flex-col gap-1">
                        <span className={
                          p.invoice_email_status === "sent"
                            ? "text-emerald-700"
                            : p.invoice_email_status === "failed"
                              ? "text-rose-600"
                              : "text-slate-500"
                        }>
                          {p.invoice_email_status === "sent"
                            ? `✓ emailed${p.invoice_email_sent_at
                                ? " " + new Date(p.invoice_email_sent_at)
                                    .toLocaleDateString() : ""}`
                            : p.invoice_email_status === "failed"
                              ? "✗ email failed"
                              : p.invoice_email_status === "queued"
                                ? "queued…"
                                : "not emailed"}
                        </span>
                        <span className="flex gap-2">
                          <button onClick={() => downloadInvoice(p)}
                                  disabled={busyInvoice === p.id}
                                  className="text-indigo-600 hover:underline
                                             disabled:opacity-40">
                            PDF
                          </button>
                          <button onClick={() => resendInvoice(p)}
                                  disabled={busyInvoice === p.id}
                                  className="text-indigo-600 hover:underline
                                             disabled:opacity-40">
                            {p.invoice_email_status === "sent"
                              ? "Resend" : "Send"}
                          </button>
                        </span>
                      </div>
                    ) : (
                      <button onClick={() => markPaid(p)}
                              disabled={busyInvoice === p.id}
                              title="Money arrived at the gateway (e.g. accepted in PayPal) but this row shows unpaid/failed — capture it, grant access, email the invoice"
                              className="text-emerald-700 hover:underline
                                         disabled:opacity-40">
                        Mark paid + invoice
                      </button>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600 whitespace-nowrap">
                    {p.created_at ? new Date(p.created_at).toLocaleString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > limit && (
        <div className="flex items-center gap-3 mt-4 text-sm">
          <button disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - limit))}
                  className="px-3 py-1.5 border border-slate-300 rounded
                             disabled:opacity-40">← Prev</button>
          <span className="text-slate-500">
            {offset + 1}–{Math.min(offset + limit, total)} of {total}
          </span>
          <button disabled={offset + limit >= total}
                  onClick={() => setOffset(offset + limit)}
                  className="px-3 py-1.5 border border-slate-300 rounded
                             disabled:opacity-40">Next →</button>
        </div>
      )}
    </div>
  );
}
