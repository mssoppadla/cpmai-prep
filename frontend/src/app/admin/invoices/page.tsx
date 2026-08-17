"use client";
/**
 * Ad-hoc invoices — generate an invoice for a sale that happened fully
 * off-platform (bank transfer, cash, a gateway payment with no cpmai
 * order). Same PDF layout, numbering style (separate INV-YYYY-M#####
 * series), email templates and CC list as automatic payment invoices.
 */
import { useCallback, useEffect, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type { AdhocInvoiceOut } from "@/types/api";

const blank = {
  buyer_name: "", buyer_email: "", description: "",
  amount: "", currency: "INR", gateway_reference: "", send_email: true,
};

export default function AdminInvoicesPage() {
  const [rows, setRows] = useState<AdhocInvoiceOut[] | null>(null);
  const [total, setTotal] = useState(0);
  const [form, setForm] = useState<typeof blank | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const p = await admin.adhocInvoices.list({ limit: 100 });
      setRows(p.items); setTotal(p.total);
    } catch (e) { setErr(errMsg(e)); }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  async function submit() {
    if (!form) return;
    const amt = Number(form.amount);
    if (!form.buyer_name.trim() || !form.buyer_email.includes("@")
        || form.description.trim().length < 3
        || !Number.isFinite(amt) || amt <= 0) {
      setErr("Fill buyer name, a valid email, a description, and a "
             + "positive amount.");
      return;
    }
    setBusy(true); setErr(null); setNotice(null);
    try {
      const r = await admin.adhocInvoices.create({
        buyer_name: form.buyer_name.trim(),
        buyer_email: form.buyer_email.trim(),
        description: form.description.trim(),
        amount_minor: Math.round(amt * 100),
        currency: form.currency.trim().toUpperCase() || "INR",
        gateway_reference: form.gateway_reference.trim() || undefined,
        send_email: form.send_email,
      });
      setNotice(`Invoice ${r.invoice_number} created`
        + (form.send_email
          ? (r.email_sent ? " and emailed." : " — email FAILED (check SMTP).")
          : "."));
      setForm(null);
      await reload();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function downloadPdf(inv: AdhocInvoiceOut) {
    try {
      const blob = await admin.adhocInvoices.downloadPdf(inv.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `${inv.invoice_number}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setErr(errMsg(e)); }
  }

  async function sendMail(inv: AdhocInvoiceOut) {
    setBusy(true); setErr(null);
    try {
      const r = await admin.adhocInvoices.send(inv.id);
      if (!r.sent) setErr("Email failed to send — check SMTP settings.");
      await reload();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  const input = "w-full mt-0.5 px-2 py-1.5 border border-slate-300 "
    + "rounded text-sm";

  return (
    <div className="p-8 max-w-5xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Invoices</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Ad-hoc invoices for off-platform sales — same format, number
            series (M), email templates and CC list as the automatic
            payment invoices. Payment-linked invoices live on the{" "}
            <a href="/admin/payments"
               className="text-indigo-600 hover:underline">Payments</a>{" "}
            screen.
          </p>
        </div>
        <button onClick={() => setForm(form ? null : { ...blank })}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg
                           text-sm hover:bg-indigo-700">
          {form ? "Cancel" : "+ Create invoice"}
        </button>
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200
                                     text-rose-700 p-3 rounded-lg mb-4
                                     text-sm">{err}</div>
      )}
      {notice && (
        <div className="bg-emerald-50 border border-emerald-200
                        text-emerald-700 p-3 rounded-lg mb-4 text-sm">
          {notice}
        </div>
      )}

      {form && (
        <div className="bg-white rounded-xl border-2 border-indigo-200 p-6
                        mb-6 space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs text-slate-600">Buyer name</span>
              <input value={form.buyer_name} className={input}
                     onChange={(e) =>
                       setForm({ ...form, buyer_name: e.target.value })} />
            </label>
            <label className="block">
              <span className="text-xs text-slate-600">Buyer email</span>
              <input value={form.buyer_email} type="email" className={input}
                     onChange={(e) =>
                       setForm({ ...form, buyer_email: e.target.value })} />
            </label>
          </div>
          <label className="block">
            <span className="text-xs text-slate-600">
              Description (what was sold — plan/bundle/live class)
            </span>
            <input value={form.description} className={input}
                   placeholder="e.g. CPMAI Exam Bundle — Exam Bundle"
                   onChange={(e) =>
                     setForm({ ...form, description: e.target.value })} />
          </label>
          <div className="grid grid-cols-3 gap-3">
            <label className="block">
              <span className="text-xs text-slate-600">
                Amount received (major units, e.g. 999.00)
              </span>
              <input value={form.amount} type="number" min={0} step="0.01"
                     className={input}
                     onChange={(e) =>
                       setForm({ ...form, amount: e.target.value })} />
            </label>
            <label className="block">
              <span className="text-xs text-slate-600">Currency</span>
              <input value={form.currency} maxLength={8} className={input}
                     onChange={(e) => setForm({
                       ...form, currency: e.target.value.toUpperCase() })} />
            </label>
            <label className="block">
              <span className="text-xs text-slate-600">
                Gateway/bank ref (optional)
              </span>
              <input value={form.gateway_reference} className={input}
                     placeholder="pay_… / PayPal txn / UPI RRN"
                     onChange={(e) => setForm({
                       ...form, gateway_reference: e.target.value })} />
            </label>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.send_email}
                   onChange={(e) =>
                     setForm({ ...form, send_email: e.target.checked })} />
            <span className="text-xs text-slate-700">
              Email the PDF to the buyer now (CCs the configured owner
              addresses)
            </span>
          </label>
          <div className="flex justify-end">
            <button onClick={submit} disabled={busy}
                    className="px-4 py-2 bg-indigo-600 text-white rounded
                               text-sm hover:bg-indigo-700
                               disabled:opacity-50">
              Create{form.send_email ? " + send" : ""}
            </button>
          </div>
        </div>
      )}

      {!rows ? (
        <div className="text-slate-500">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12
                        text-center text-slate-500">
          No ad-hoc invoices yet. Use “+ Create invoice” for off-platform
          sales.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200
                        overflow-x-auto">
          <table className="w-full min-w-[56rem]">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500
                             uppercase">
                <th className="px-4 py-3">Invoice #</th>
                <th className="px-4 py-3">Buyer</th>
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">Amount</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((inv) => (
                <tr key={inv.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-xs font-mono
                                 text-slate-700">
                    {inv.invoice_number}
                    <span className="flex gap-2 mt-1">
                      <button onClick={() => downloadPdf(inv)}
                              className="text-indigo-600 hover:underline">
                        PDF
                      </button>
                      <button onClick={() => sendMail(inv)} disabled={busy}
                              className="text-indigo-600 hover:underline
                                         disabled:opacity-40">
                        {inv.email_status === "sent" ? "Resend" : "Send"}
                      </button>
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <div className="text-slate-900">{inv.buyer_name}</div>
                    <div className="text-xs text-slate-500">
                      {inv.buyer_email}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-700
                                 max-w-[18rem]">
                    {inv.description}
                    {inv.gateway_reference && (
                      <div className="text-[10px] text-slate-400">
                        ref: {inv.gateway_reference}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-900
                                 whitespace-nowrap">
                    {inv.currency} {(inv.amount_minor / 100).toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {inv.email_status === "sent" ? (
                      <span className="text-emerald-700">
                        ✓ sent{inv.email_sent_at
                          ? " " + new Date(inv.email_sent_at)
                              .toLocaleDateString() : ""}
                      </span>
                    ) : inv.email_status === "failed" ? (
                      <span className="text-rose-600">✗ failed</span>
                    ) : (
                      <span className="text-slate-400">not sent</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600
                                 whitespace-nowrap">
                    {inv.created_at
                      ? new Date(inv.created_at).toLocaleString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {total > 100 && (
        <p className="text-xs text-slate-500 mt-2">
          Showing the latest 100 of {total}.
        </p>
      )}
    </div>
  );
}
