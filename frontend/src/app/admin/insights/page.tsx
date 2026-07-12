"use client";
/**
 * /admin/insights — Visitor Insights v2 dashboard.
 *
 * Three sections, each backed by a /admin/insights/* endpoint:
 *
 *   1. KPI strip      — overview() — sessions / visitors / avg duration
 *                       / pages-per-session / bounce / conversion
 *   2. Top pages      — pages()    — table of paths sorted by views,
 *                       with avg active time, bounce %, exit %
 *   3. Conversion     — funnel()   — landing → signup → first lesson →
 *                       payment; absolute counts + step-to-step %
 *
 * Plus a drilldown panel: pick a visitor (anon_id) from the URL or
 * paste one, see their full event timeline in order. Convenient when
 * the operator wants to investigate a specific lead or bounce — they
 * grab the anon_id from /admin/leads and pop it in here.
 *
 * The old /admin/anonymous-traffic widget on /admin/leads stays put
 * (operator may still want a quick view there) but a "Open full
 * insights" link now sits above it pointing here.
 */
import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { admin, errMsg } from "@/lib/api";


type Window = "24h" | "7d" | "30d" | "90d";

const WINDOW_OPTIONS: { value: Window; label: string }[] = [
  { value: "24h", label: "Last 24 hours" },
  { value: "7d",  label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
];

function fmtSeconds(s: number): string {
  if (s < 60) return `${s.toFixed(0)}s`;
  if (s < 3600) return `${(s / 60).toFixed(1)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}
function fmtPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`;
}


export default function InsightsPage() {
  const [win, setWin] = useState<Window>("7d");
  const [overview, setOverview] = useState<Awaited<ReturnType<typeof admin.insights.overview>> | null>(null);
  const [pages,    setPages]    = useState<Awaited<ReturnType<typeof admin.insights.pages>> | null>(null);
  const [funnel,   setFunnel]   = useState<Awaited<ReturnType<typeof admin.insights.funnel>> | null>(null);
  const [flow,     setFlow]     = useState<Awaited<ReturnType<typeof admin.insights.flow>> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Session drilldown
  const [anonId, setAnonId] = useState("");
  const [drill,  setDrill]  = useState<Awaited<ReturnType<typeof admin.insights.session>> | null>(null);
  const [drillErr, setDrillErr] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setErr(null); setLoading(true);
    try {
      const [o, p, f, fl] = await Promise.all([
        admin.insights.overview(win),
        admin.insights.pages(win, 25),
        admin.insights.funnel(win),
        admin.insights.flow(win, 25),
      ]);
      setOverview(o); setPages(p); setFunnel(f); setFlow(fl);
    } catch (e) {
      setErr(errMsg(e));
    } finally { setLoading(false); }
  }, [win]);
  useEffect(() => { void reload(); }, [reload]);

  async function loadDrill() {
    if (!anonId.trim()) return;
    setDrillErr(null); setDrill(null);
    try {
      setDrill(await admin.insights.session(anonId.trim()));
    } catch (e) {
      setDrillErr(errMsg(e));
    }
  }

  async function anonymize() {
    if (!anonId.trim()) return;
    if (!confirm(`Permanently anonymise this visitor (${anonId})? ` +
                 `Their event rows stay (aggregates unchanged) but no ` +
                 `further drilldown by this ID will be possible.`)) return;
    try {
      const res = await admin.insights.anonymize(anonId.trim());
      alert(`Anonymised ${res.rows_affected} row(s).`);
      setDrill(null);
    } catch (e) {
      alert(errMsg(e));
    }
  }

  return (
    <div className="max-w-7xl mx-auto p-6 space-y-8">
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Visitor Insights</h1>
          <p className="text-sm text-slate-500">
            Page-level + funnel analytics for both anonymous visitors
            and signed-in users. Powered by the journey_events stream.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={win}
            onChange={(e) => setWin(e.target.value as Window)}
            className="text-sm rounded border px-2 py-1"
          >
            {WINDOW_OPTIONS.map((o) =>
              <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <Link href="/admin/leads"
                className="text-sm text-blue-600 hover:underline">
            Leads ↗
          </Link>
        </div>
      </header>

      {err && (
        <div className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">
          {err}
        </div>
      )}

      {/* ── KPI strip ───────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-slate-700 mb-2">Overview</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
          <KpiCard label="Sessions"
                   value={overview ? String(overview.kpi.sessions) : "—"}
                   loading={loading} />
          <KpiCard label="Visitors"
                   value={overview ? String(overview.kpi.visitors) : "—"}
                   loading={loading} />
          <KpiCard label="Page views"
                   value={overview ? String(overview.kpi.page_views) : "—"}
                   loading={loading} />
          <KpiCard label="Avg session"
                   value={overview ? fmtSeconds(overview.kpi.avg_session_seconds) : "—"}
                   loading={loading} />
          <KpiCard label="Pages / session"
                   value={overview ? overview.kpi.avg_pages_per_session.toFixed(2) : "—"}
                   loading={loading} />
          <KpiCard label="Bounce rate"
                   value={overview ? fmtPct(overview.kpi.bounce_rate) : "—"}
                   loading={loading}
                   tone={overview && overview.kpi.bounce_rate > 0.6 ? "warn" : "ok"} />
          <KpiCard label="Conversion rate"
                   value={overview ? fmtPct(overview.kpi.conversion_rate) : "—"}
                   loading={loading}
                   tone={overview && overview.kpi.conversion_rate < 0.01 ? "warn" : "ok"} />
        </div>
      </section>

      {/* ── Top pages ───────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-slate-700 mb-2">Top pages</h2>
        <div className="rounded border bg-white overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="text-left p-2">Path</th>
                <th className="text-right p-2">Views</th>
                <th className="text-right p-2">Visitors</th>
                <th className="text-right p-2">Avg time</th>
                <th className="text-right p-2">Bounce %</th>
                <th className="text-right p-2">Exit %</th>
              </tr>
            </thead>
            <tbody>
              {pages?.pages.length ? pages.pages.map((p) => (
                <tr key={p.path} className="border-t hover:bg-slate-50">
                  <td className="p-2 font-mono text-xs">{p.path}</td>
                  <td className="p-2 text-right">{p.views}</td>
                  <td className="p-2 text-right">{p.unique_visitors}</td>
                  <td className="p-2 text-right">{fmtSeconds(p.avg_seconds)}</td>
                  <td className={`p-2 text-right ${p.bounce_rate > 0.7 ? "text-rose-600" : ""}`}>
                    {fmtPct(p.bounce_rate)}
                  </td>
                  <td className="p-2 text-right">{fmtPct(p.exit_rate)}</td>
                </tr>
              )) : (
                <tr><td colSpan={6} className="p-4 text-center text-slate-500">
                  {loading ? "Loading…" : "No page views in this window yet."}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Navigation flow ─────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-slate-700 mb-2">Navigation flow</h2>
        <p className="text-xs text-slate-400 mb-2">
          Where visitors go next: each row is a page-to-page move within a
          session, with the average active time spent on the page before
          moving on.
        </p>
        <div className="grid lg:grid-cols-3 gap-4 items-start">
          <div className="lg:col-span-2 rounded border bg-white overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="text-left p-2">From</th>
                  <th className="text-left p-2 w-6" aria-hidden></th>
                  <th className="text-left p-2">To</th>
                  <th className="text-right p-2">Moves</th>
                  <th className="text-right p-2" title="Share of all moves leaving the From page">% of exits</th>
                  <th className="text-right p-2" title="Average active time on the From page before moving">Time before move</th>
                </tr>
              </thead>
              <tbody>
                {flow?.transitions.length ? flow.transitions.map((t) => (
                  <tr key={`${t.from_path}→${t.to_path}`} className="border-t hover:bg-slate-50">
                    <td className="p-2 font-mono text-xs">{t.from_path}</td>
                    <td className="p-2 text-slate-400">→</td>
                    <td className="p-2 font-mono text-xs">{t.to_path}</td>
                    <td className="p-2 text-right">{t.count}</td>
                    <td className="p-2 text-right">{fmtPct(t.share_of_from)}</td>
                    <td className="p-2 text-right">
                      {t.avg_seconds_on_from ? fmtSeconds(t.avg_seconds_on_from) : "—"}
                    </td>
                  </tr>
                )) : (
                  <tr><td colSpan={6} className="p-4 text-center text-slate-500">
                    {loading ? "Loading…" : "No page-to-page moves in this window yet."}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="space-y-4">
            <PathCountCard title="Top entry pages"
                           hint="First page of a session"
                           rows={flow?.entries ?? []} loading={loading} />
            <PathCountCard title="Top exit pages"
                           hint="Last page before leaving"
                           rows={flow?.exits ?? []} loading={loading} />
          </div>
        </div>
      </section>

      {/* ── Funnel ──────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-slate-700 mb-2">
          Conversion funnel
          {funnel && funnel.overall_conversion > 0 && (
            <span className="ml-2 text-xs font-normal text-slate-500">
              · overall {fmtPct(funnel.overall_conversion)}
            </span>
          )}
        </h2>
        <div className="rounded border bg-white p-4 space-y-2">
          {funnel?.stages.length ? funnel.stages.map((s, i) => {
            const max = funnel.stages[0].visitors || 1;
            const widthPct = (s.visitors / max) * 100;
            return (
              <div key={s.label} className="flex items-center gap-3">
                <div className="w-32 text-xs text-slate-600">{s.label}</div>
                <div className="flex-1 bg-slate-100 rounded h-6 overflow-hidden relative">
                  <div className="bg-blue-500 h-full" style={{ width: `${widthPct}%` }} />
                  <div className="absolute inset-0 flex items-center justify-end pr-2 text-xs text-slate-700">
                    {s.visitors.toLocaleString()}
                    {i > 0 && s.conversion_from_prev != null && (
                      <span className="ml-2 text-slate-400">
                        ({fmtPct(s.conversion_from_prev)} of prev)
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          }) : (
            <div className="p-2 text-center text-slate-500 text-sm">
              {loading ? "Loading…" : "No funnel data in this window yet."}
            </div>
          )}
        </div>
      </section>

      {/* ── Session drilldown ───────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-slate-700 mb-2">
          Visitor drilldown
        </h2>
        <div className="rounded border bg-white p-4 space-y-3">
          <div className="flex gap-2 flex-wrap">
            <input
              value={anonId}
              onChange={(e) => setAnonId(e.target.value)}
              placeholder="Paste anon_id (UUID) — found on /admin/leads rows"
              className="flex-1 min-w-[260px] rounded border px-2 py-1 text-sm font-mono"
            />
            <button onClick={loadDrill}
                    className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700">
              Load timeline
            </button>
            {drill && (
              <button onClick={anonymize}
                      className="rounded border border-rose-300 px-3 py-1 text-sm text-rose-700 hover:bg-rose-50"
                      title="GDPR — unlink this visitor from their event rows">
                Anonymise
              </button>
            )}
          </div>

          {drillErr && (
            <div className="text-sm text-rose-700">{drillErr}</div>
          )}

          {drill && (
            <div className="space-y-2">
              <div className="text-xs text-slate-500">
                {drill.event_count} events · first seen {drill.first_seen.slice(0, 19).replace("T", " ")} ·
                last seen {drill.last_seen.slice(0, 19).replace("T", " ")}
                {drill.linked_user_ids.length > 0 && (
                  <span className="ml-2">
                    · linked user(s): {drill.linked_user_ids.join(", ")}
                  </span>
                )}
              </div>
              <ol className="border rounded divide-y max-h-[480px] overflow-y-auto bg-slate-50">
                {drill.events.map((e) => (
                  <li key={e.id} className="p-2 text-xs grid grid-cols-12 gap-2">
                    <span className="col-span-2 font-mono text-slate-500">
                      {e.at.slice(11, 19)}
                    </span>
                    <span className="col-span-2 font-semibold">{e.event}</span>
                    <span className="col-span-4 font-mono text-slate-700 truncate">
                      {e.path || "—"}
                    </span>
                    <span className="col-span-2 text-slate-500 truncate">
                      {[e.device, e.browser, e.os].filter(Boolean).join(" / ")}
                    </span>
                    <span className="col-span-2 text-slate-500 truncate">
                      {e.country || ""}{e.city ? ` · ${e.city}` : ""}
                      {e.duration_ms ? ` · ${(e.duration_ms / 1000).toFixed(0)}s` : ""}
                      {e.scroll_pct ? ` · ${e.scroll_pct}%↓` : ""}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}


function PathCountCard({ title, hint, rows, loading }: {
  title: string;
  hint: string;
  rows: { path: string; count: number }[];
  loading?: boolean;
}) {
  const max = rows[0]?.count || 1;
  return (
    <div className="rounded border bg-white p-3">
      <div className="text-xs font-semibold text-slate-700">{title}</div>
      <div className="text-[11px] text-slate-400 mb-2">{hint}</div>
      {rows.length ? (
        <div className="space-y-1.5">
          {rows.map((r) => (
            <div key={r.path} className="flex items-center gap-2 text-xs">
              <span className="font-mono truncate flex-1">{r.path}</span>
              <div className="w-20 bg-slate-100 rounded h-2 overflow-hidden flex-shrink-0">
                <div className="bg-indigo-400 h-full" style={{ width: `${(r.count / max) * 100}%` }} />
              </div>
              <span className="w-8 text-right text-slate-600 tabular-nums">{r.count}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs text-slate-400">{loading ? "Loading…" : "No data yet."}</div>
      )}
    </div>
  );
}

function KpiCard({ label, value, loading, tone = "ok" }: {
  label: string;
  value: string;
  loading?: boolean;
  tone?: "ok" | "warn";
}) {
  const toneCls = tone === "warn"
    ? "border-amber-300 bg-amber-50"
    : "bg-white";
  return (
    <div className={`rounded border ${toneCls} px-3 py-2`}>
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-xl font-semibold text-slate-800">
        {loading && value === "—" ? "…" : value}
      </div>
    </div>
  );
}
