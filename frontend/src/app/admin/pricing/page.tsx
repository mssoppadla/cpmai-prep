"use client";
/**
 * /admin/pricing — international-pricing operational dashboard.
 *
 * Three cards:
 *
 *   1. Cron status — last-fetched timestamp, age, stale flag,
 *      manual "Refresh now" button (rate-limited to 5/hr server-side).
 *   2. Markup + overrides — admin edits ``pricing.fx_markup_percent``
 *      and ``pricing.fx_overrides`` via the same SettingsStore flow
 *      the /admin/settings page uses. Live-edited values reflected
 *      in the rates table below on next reload.
 *   3. Effective rates table — per-currency: code, source (live /
 *      override / stale / inr), raw mid-market, effective (post-markup)
 *      rate, whether it's in the public picker.
 *
 * The page is read-mostly. Edits to markup/overrides flow through
 * /admin/settings PATCH — we don't duplicate that endpoint here.
 */
import { useCallback, useEffect, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type {
  FXStatusOut, FXRefreshOut, SettingOut,
} from "@/types/api";


export default function AdminPricingPage() {
  const [status, setStatus] = useState<FXStatusOut | null>(null);
  const [markupSetting, setMarkupSetting] = useState<SettingOut | null>(null);
  const [overridesSetting, setOverridesSetting] = useState<SettingOut | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setErr(null);
    try {
      const [fx, allSettings] = await Promise.all([
        admin.pricing.fxStatus(),
        admin.settings.list(),
      ]);
      setStatus(fx);
      const m = allSettings.find(s => s.key === "pricing.fx_markup_percent");
      const o = allSettings.find(s => s.key === "pricing.fx_overrides");
      setMarkupSetting(m ?? null);
      setOverridesSetting(o ?? null);
    } catch (e) {
      setErr(errMsg(e));
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  return (
    <div className="p-8 max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">International pricing</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Live FX rates from{" "}
          <a href="https://api.frankfurter.dev" target="_blank" rel="noreferrer"
             className="text-indigo-600 hover:underline">Frankfurter</a>
          {" "}(ECB-published, free, daily). Markup is applied at quote-time
          and shown to international buyers as a transparent "processing
          fee" line — not baked into the rate.
        </p>
      </header>

      {err && (
        <div role="alert"
             className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg text-sm">
          {err}
        </div>
      )}

      <CronStatusCard status={status} onRefreshed={reload} />

      <MarkupOverridesCard
        markupSetting={markupSetting}
        overridesSetting={overridesSetting}
        onSaved={reload}
      />

      <RatesTableCard status={status} />
    </div>
  );
}


// ============================================================ Cron card

function CronStatusCard({
  status, onRefreshed,
}: { status: FXStatusOut | null; onRefreshed: () => void }) {
  const [busy, setBusy] = useState(false);
  const [refreshResult, setRefreshResult] = useState<FXRefreshOut | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  async function refresh() {
    setBusy(true); setRefreshResult(null); setRefreshError(null);
    try {
      setRefreshResult(await admin.pricing.fxRefreshNow());
      onRefreshed();
    } catch (e) {
      setRefreshError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-white rounded-xl border border-slate-200 p-6 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">
          Live FX cron
        </h2>
        {status && (
          status.stale ? (
            <span className="text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
              ⚠ STALE (&gt;7 days)
            </span>
          ) : status.last_fetched_at ? (
            <span className="text-xs px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">
              ✓ Fresh
            </span>
          ) : (
            <span className="text-xs px-2 py-0.5 rounded bg-slate-50 text-slate-600 border border-slate-200">
              Never fetched
            </span>
          )
        )}
      </div>

      {!status ? (
        <div className="text-sm text-slate-500">Loading…</div>
      ) : (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <dt className="text-slate-500">Last fetched (UTC)</dt>
          <dd className="text-slate-800">
            {status.last_fetched_at
              ? new Date(status.last_fetched_at).toLocaleString()
              : "—"}
          </dd>
          <dt className="text-slate-500">Age</dt>
          <dd className={status.stale ? "text-amber-700 font-medium" : "text-slate-800"}>
            {status.age_days != null ? `${status.age_days.toFixed(2)} days` : "—"}
          </dd>
          <dt className="text-slate-500">Markup applied</dt>
          <dd className="text-slate-800">{status.markup_percent.toFixed(1)}%</dd>
          <dt className="text-slate-500">Currencies with rates</dt>
          <dd className="text-slate-800">
            {status.currencies.filter(c => c.has_live_rate).length}
          </dd>
        </dl>
      )}

      <div className="pt-3 border-t border-slate-100 flex items-center gap-3 flex-wrap">
        <button onClick={refresh} disabled={busy}
                className="px-3 py-1.5 bg-indigo-600 text-white text-sm rounded
                           hover:bg-indigo-700 disabled:opacity-50">
          {busy ? "Refreshing…" : "Refresh now"}
        </button>
        <span className="text-xs text-slate-500">
          Daily cron at 04:23 UTC; manual button rate-limited to 5/hr.
        </span>
        {refreshResult && (
          <div className="text-sm text-emerald-700 w-full">
            ✓ {refreshResult.message}
            {refreshResult.rejected_codes.length > 0 && (
              <div className="text-xs text-amber-700 mt-0.5">
                ⚠ Sanity cap kept these unchanged:{" "}
                {refreshResult.rejected_codes.join(", ")}
              </div>
            )}
          </div>
        )}
        {refreshError && (
          <div className="text-sm text-rose-700 w-full">✗ {refreshError}</div>
        )}
      </div>
    </section>
  );
}


// ====================================================== Markup + overrides

function MarkupOverridesCard({
  markupSetting, overridesSetting, onSaved,
}: {
  markupSetting: SettingOut | null;
  overridesSetting: SettingOut | null;
  onSaved: () => void;
}) {
  return (
    <section className="bg-white rounded-xl border border-slate-200 p-6 space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">
          Markup &amp; overrides
        </h2>
        <p className="text-xs text-slate-500 mt-1">
          Edit these through Runtime Settings — they propagate within ~30
          seconds and reflect on the next /pricing page load.{" "}
          <a href="/admin/settings" className="text-indigo-600 hover:underline">
            Edit in /admin/settings →
          </a>
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4 text-sm">
        <div className="text-slate-500">Markup percent</div>
        <div className="col-span-2">
          <code className="px-2 py-0.5 bg-slate-100 rounded font-mono text-slate-800">
            {markupSetting ? JSON.stringify(markupSetting.value) : "—"}%
          </code>
          <span className="text-xs text-slate-500 ml-2">
            Default 5%. Applied to live mid-market rates at quote time;
            shown to international buyers as a separate fee line.
          </span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 text-sm">
        <div className="text-slate-500">Overrides</div>
        <div className="col-span-2">
          <code className="px-2 py-0.5 bg-slate-100 rounded font-mono text-slate-800 break-all">
            {overridesSetting
              ? JSON.stringify(overridesSetting.value || {})
              : "{}"}
          </code>
          <p className="text-xs text-slate-500 mt-1">
            Currency → INR-per-1-unit. Wins over live rates. Markup is NOT
            applied (admin's value is final). Use for currencies Razorpay
            supports but Frankfurter doesn't cover (AED, SAR, KWD), or
            for promo pricing in a specific country at a fixed rate.
          </p>
        </div>
      </div>
    </section>
  );
}


// ====================================================== Rates table

function RatesTableCard({ status }: { status: FXStatusOut | null }) {
  return (
    <section className="bg-white rounded-xl border border-slate-200 p-6 space-y-3">
      <h2 className="text-lg font-semibold text-slate-900">
        Effective rates
      </h2>
      {!status ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : status.currencies.length === 0 ? (
        <p className="text-sm text-slate-500">
          No currencies configured yet. Click "Refresh now" above to pull
          live rates from Frankfurter, or add a manual override in
          Runtime Settings.
        </p>
      ) : (
        <div className="overflow-x-auto border border-slate-200 rounded">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase">
                <th className="px-3 py-2">Code</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2">Mid-market</th>
                <th className="px-3 py-2">Effective (incl. markup)</th>
                <th className="px-3 py-2">Picker</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {status.currencies.map(c => (
                <tr key={c.code} className="hover:bg-slate-50">
                  <td className="px-3 py-2">
                    <code className="font-mono text-slate-800">
                      {c.symbol} {c.code}
                    </code>
                  </td>
                  <td className="px-3 py-2">
                    <SourceBadge source={c.source} />
                  </td>
                  <td className="px-3 py-2 text-slate-700">
                    {c.raw_inr_per_unit != null
                      ? `₹${c.raw_inr_per_unit.toFixed(2)}`
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-slate-800 font-medium">
                    {c.effective_inr_per_unit != null
                      ? `₹${c.effective_inr_per_unit.toFixed(2)}`
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {c.in_picker
                      ? <span className="text-emerald-700">✓ shown</span>
                      : <span className="text-slate-400">hidden</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}


function SourceBadge({ source }: { source: string }) {
  const styles: Record<string, string> = {
    inr:         "bg-slate-100 text-slate-700 border-slate-200",
    live:        "bg-emerald-50 text-emerald-700 border-emerald-200",
    override:    "bg-indigo-50 text-indigo-700 border-indigo-200",
    stale:       "bg-amber-50 text-amber-700 border-amber-200",
    unavailable: "bg-rose-50 text-rose-700 border-rose-200",
  };
  const klass = styles[source] || styles.unavailable;
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${klass}`}>
      {source}
    </span>
  );
}
