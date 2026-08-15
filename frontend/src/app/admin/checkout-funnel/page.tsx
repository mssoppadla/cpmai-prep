"use client";
import { useCallback, useEffect, useState } from "react";
import { admin, errMsg, type CheckoutFunnelOut, type FunnelUser } from "@/lib/api";

/**
 * /admin/checkout-funnel — "Checkout Follow-ups".
 *
 * Who almost paid: failed/abandoned orders WITH contact details, plus
 * pricing-page visitors who never started checkout — so the operator
 * follows up from one screen instead of stitching Payments + Visitor
 * Insights by hand. Read-only; window selector mirrors /admin/error-logs
 * so both dashboards share one mental model.
 */

const WINDOWS = [
  { label: "1 hr", minutes: 60 },
  { label: "6 hr", minutes: 360 },
  { label: "24 hr", minutes: 1440 },
  { label: "3 days", minutes: 4320 },
  { label: "7 days", minutes: 10080 },
  { label: "30 days", minutes: 43200 },
];

function money(paise: number, currency: string): string {
  const sym = currency === "INR" ? "₹" : `${currency} `;
  return `${sym}${(paise / 100).toFixed(2)}`;
}

function ContactCell({ user, anonId }: { user: FunnelUser | null; anonId?: string | null }) {
  if (!user) {
    return (
      <span className="text-xs text-slate-500" title={anonId ?? undefined}>
        anonymous{anonId ? ` · ${anonId.slice(0, 8)}…` : ""}
      </span>
    );
  }
  return (
    <div className="min-w-0">
      <div className="text-sm font-medium text-slate-900 truncate">
        {user.name || user.email}
      </div>
      <div className="text-xs text-slate-500 flex flex-wrap gap-x-2">
        <a href={`mailto:${user.email}`} className="text-indigo-600 hover:underline">{user.email}</a>
        {user.whatsapp && (
          <a href={`https://wa.me/${user.whatsapp.replace(/[^0-9]/g, "")}`}
             target="_blank" rel="noopener noreferrer"
             className="text-emerald-700 hover:underline">WhatsApp</a>
        )}
        {user.linkedin_id && (
          <a href={`https://www.linkedin.com/in/${encodeURIComponent(user.linkedin_id)}`}
             target="_blank" rel="noopener noreferrer"
             className="text-sky-700 hover:underline">LinkedIn</a>
        )}
      </div>
    </div>
  );
}

export default function CheckoutFunnelPage() {
  const [minutes, setMinutes] = useState(1440);
  const [data, setData] = useState<CheckoutFunnelOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try { setData(await admin.checkoutFunnel.get(minutes)); }
    catch (e) { setErr(errMsg(e)); }
    finally { setLoading(false); }
  }, [minutes]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Checkout Follow-ups</h1>
          <p className="text-sm text-slate-500">
            Payments that didn&apos;t complete (with contact details) and pricing
            visitors who never started checkout.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={minutes}
            onChange={(e) => setMinutes(parseInt(e.target.value, 10))}
            className="px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white"
            aria-label="Look-back window"
          >
            {WINDOWS.map((w) => (
              <option key={w.minutes} value={w.minutes}>Last {w.label}</option>
            ))}
          </select>
          <button onClick={() => void load()} disabled={loading}
                  className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50">
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {err && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg text-sm">{err}</div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Pricing visitors" value={data.summary.visitors} />
            <Stat label="Checkouts started" value={data.summary.started} />
            <Stat label="Paid" value={data.summary.captured} tone="good" />
            <Stat label="Need follow-up" value={data.summary.needs_followup} tone="warn" />
          </div>

          {/* Section 1 — the money list */}
          <div className="bg-white rounded-xl border border-amber-200 p-4">
            <h2 className="text-sm font-semibold text-amber-800 mb-3">
              ⚠️ Started checkout, didn&apos;t complete
              <span className="ml-2 font-normal text-slate-400">
                failed attempts + orders abandoned &gt;15 min
              </span>
            </h2>
            {data.needs_followup.length === 0 ? (
              <div className="text-sm text-slate-400">Nothing needs follow-up in this window. 🎉</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-500 border-b border-slate-200">
                      <th className="py-2 pr-3">Who</th>
                      <th className="py-2 pr-3">Plan</th>
                      <th className="py-2 pr-3">Amount</th>
                      <th className="py-2 pr-3">Status</th>
                      <th className="py-2">When</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.needs_followup.map((r) => (
                      <tr key={r.payment_id}>
                        <td className="py-2 pr-3"><ContactCell user={r.user} /></td>
                        <td className="py-2 pr-3">{r.plan_name ?? "—"}</td>
                        <td className="py-2 pr-3 tabular-nums">{money(r.amount_paise, r.currency)}</td>
                        <td className="py-2 pr-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full border ${
                            r.status === "failed"
                              ? "bg-rose-50 text-rose-700 border-rose-200"
                              : "bg-amber-50 text-amber-700 border-amber-200"}`}>
                            {r.status === "failed" ? "failed" : "abandoned"}
                          </span>
                        </td>
                        <td className="py-2 text-xs text-slate-500 whitespace-nowrap">
                          {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Section 2 — looked, never started */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <h2 className="text-sm font-semibold text-slate-700 mb-3">
              Visited pricing, never started checkout
            </h2>
            {data.pricing_visitors.length === 0 ? (
              <div className="text-sm text-slate-400">No pricing visitors without checkout in this window.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[680px] text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-500 border-b border-slate-200">
                      <th className="py-2 pr-3">Who</th>
                      <th className="py-2 pr-3">Where</th>
                      <th className="py-2 pr-3">Device</th>
                      <th className="py-2 pr-3">Source</th>
                      <th className="py-2">Last seen</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.pricing_visitors.map((v, i) => (
                      <tr key={v.user?.id ?? v.anon_id ?? i}>
                        <td className="py-2 pr-3"><ContactCell user={v.user} anonId={v.anon_id} /></td>
                        <td className="py-2 pr-3 text-xs text-slate-500">
                          {[v.city, v.country].filter(Boolean).join(", ") || "—"}
                        </td>
                        <td className="py-2 pr-3 text-xs text-slate-500">{v.device ?? "—"}</td>
                        <td className="py-2 pr-3 text-xs text-slate-500">{v.utm_source ?? "—"}</td>
                        <td className="py-2 text-xs text-slate-500 whitespace-nowrap">
                          {v.last_seen_at ? new Date(v.last_seen_at).toLocaleString() : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number;
                                        tone?: "good" | "warn" }) {
  const color = tone === "good" ? "text-emerald-700"
    : tone === "warn" ? "text-amber-700" : "text-slate-900";
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className={`text-2xl font-bold tabular-nums ${color}`}>{value}</div>
      <div className="text-xs text-slate-500 mt-0.5">{label}</div>
    </div>
  );
}
