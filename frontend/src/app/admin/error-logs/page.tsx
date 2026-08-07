"use client";
import { useCallback, useEffect, useState } from "react";
import { admin, errMsg, type ErrorLogSummary, type ErrorLogRow } from "@/lib/api";

/**
 * /admin/error-logs — live view of client-reported errors.
 *
 * These are failures the backend can't log itself: requests that died on
 * the wire (QUIC stalls, dropped connections, DNS) plus uncaught JS
 * errors. Window and auto-refresh cadence are both admin-configurable —
 * mid-incident you set 5m + 30s auto-refresh for a war-room view; on a
 * quiet day 24h + off. Choices persist per browser.
 */

const WINDOWS = [
  { label: "5 min",  minutes: 5 },
  { label: "10 min", minutes: 10 },
  { label: "30 min", minutes: 30 },
  { label: "1 hr",   minutes: 60 },
  { label: "6 hr",   minutes: 360 },
  { label: "24 hr",  minutes: 1440 },
  { label: "7 days", minutes: 10080 },
];

const REFRESH = [
  { label: "Auto-refresh off", seconds: 0 },
  { label: "Every 30s",        seconds: 30 },
  { label: "Every 1 min",      seconds: 60 },
  { label: "Every 5 min",      seconds: 300 },
];

const WINDOW_KEY  = "cpmai.admin.errlogs.window";
const REFRESH_KEY = "cpmai.admin.errlogs.refresh";

export default function AdminErrorLogsPage() {
  const [minutes, setMinutes] = useState(60);
  const [refreshSec, setRefreshSec] = useState(0);
  const [summary, setSummary] = useState<ErrorLogSummary | null>(null);
  const [rows, setRows] = useState<ErrorLogRow[]>([]);
  const [total, setTotal] = useState(0);
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [lastLoaded, setLastLoaded] = useState<Date | null>(null);

  // Restore persisted prefs once on mount.
  useEffect(() => {
    try {
      const w = parseInt(localStorage.getItem(WINDOW_KEY) ?? "", 10);
      if (WINDOWS.some((x) => x.minutes === w)) setMinutes(w);
      const r = parseInt(localStorage.getItem(REFRESH_KEY) ?? "", 10);
      if (REFRESH.some((x) => x.seconds === r)) setRefreshSec(r);
    } catch { /* defaults are fine */ }
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const [s, l] = await Promise.all([
        admin.errorLogs.summary(minutes),
        admin.errorLogs.list({ minutes, source: source || undefined, limit: 200 }),
      ]);
      setSummary(s); setRows(l.rows); setTotal(l.total);
      setLastLoaded(new Date());
    } catch (e) { setErr(errMsg(e)); }
    finally { setLoading(false); }
  }, [minutes, source]);

  // Reload when window/filter changes, and on the admin-chosen cadence.
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (refreshSec === 0) return;
    const iv = setInterval(() => void load(), refreshSec * 1000);
    return () => clearInterval(iv);
  }, [refreshSec, load]);

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Error logs</h1>
          <p className="text-sm text-slate-500">
            Client-reported failures — network drops, QUIC stalls, 5xx responses,
            and uncaught JS errors. These never appear in server logs, so this is
            the user-pain view.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={minutes}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              setMinutes(v);
              try { localStorage.setItem(WINDOW_KEY, String(v)); } catch {}
            }}
            className="px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white"
            aria-label="Look-back window"
          >
            {WINDOWS.map((w) => (
              <option key={w.minutes} value={w.minutes}>Last {w.label}</option>
            ))}
          </select>
          <select
            value={refreshSec}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              setRefreshSec(v);
              try { localStorage.setItem(REFRESH_KEY, String(v)); } catch {}
            }}
            className="px-3 py-2 text-sm border border-slate-300 rounded-lg bg-white"
            aria-label="Auto-refresh frequency"
          >
            {REFRESH.map((r) => (
              <option key={r.seconds} value={r.seconds}>{r.label}</option>
            ))}
          </select>
          <button
            onClick={() => void load()}
            disabled={loading}
            className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? "Refreshing…" : "Refresh now"}
          </button>
        </div>
      </div>

      {lastLoaded && (
        <div className="text-xs text-slate-400">
          Last checked {lastLoaded.toLocaleTimeString()}
          {refreshSec > 0 && ` · auto-refreshing every ${refreshSec}s`}
        </div>
      )}

      {err && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg text-sm">
          {err}
        </div>
      )}

      {summary && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Errors" value={summary.total} />
            <StatCard label="Signed-in users affected" value={summary.affected_users} />
            <StatCard label="Anonymous visitors affected" value={summary.affected_anons} />
            <StatCard label="Window" value={`${summary.window_minutes} min`} />
          </div>

          <div className="grid sm:grid-cols-2 gap-3">
            <TopList title="Top error types"
                     items={summary.top_types.map((t) => ({ k: t.error_type, n: t.count }))} />
            <TopList title="Top failing paths"
                     items={summary.top_paths.map((t) => ({ k: t.path, n: t.count }))} />
          </div>
        </>
      )}

      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-700">
            Latest errors <span className="font-normal text-slate-400">· {total} in window</span>
          </h2>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="px-2 py-1.5 text-xs border border-slate-300 rounded-lg bg-white"
            aria-label="Filter by source"
          >
            <option value="">All sources</option>
            <option value="network">network</option>
            <option value="api">api (5xx)</option>
            <option value="frontend">frontend (JS)</option>
          </select>
        </div>
        {rows.length === 0 ? (
          <div className="text-sm text-slate-400">
            No errors reported in this window. 🎉
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500 border-b border-slate-200">
                  <th className="py-2 pr-3">When</th>
                  <th className="py-2 pr-3">Source</th>
                  <th className="py-2 pr-3">Type</th>
                  <th className="py-2 pr-3">Path</th>
                  <th className="py-2 pr-3">Who</th>
                  <th className="py-2">Message</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="py-2 pr-3 whitespace-nowrap text-slate-500">
                      {r.created_at ? new Date(r.created_at).toLocaleTimeString() : "—"}
                    </td>
                    <td className="py-2 pr-3">
                      <span className={`text-xs px-1.5 py-0.5 rounded border ${
                        r.source === "network"
                          ? "bg-amber-50 text-amber-700 border-amber-200"
                          : r.source === "api"
                            ? "bg-rose-50 text-rose-700 border-rose-200"
                            : "bg-indigo-50 text-indigo-700 border-indigo-200"
                      }`}>
                        {r.source}
                      </span>
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {r.error_type}{r.status_code ? ` (${r.status_code})` : ""}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs max-w-[240px] truncate"
                        title={`${r.method ?? ""} ${r.path ?? ""}`}>
                      {r.method ? `${r.method} ` : ""}{r.path ?? "—"}
                    </td>
                    <td className="py-2 pr-3 text-xs text-slate-500">
                      {r.user_id ? `user ${r.user_id}` : r.anon_id ? "anon" : "—"}
                    </td>
                    <td className="py-2 text-xs text-slate-600 max-w-[300px] truncate"
                        title={r.message ?? ""}>
                      {r.message ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="text-2xl font-bold text-slate-900 tabular-nums">{value}</div>
      <div className="text-xs text-slate-500 mt-0.5">{label}</div>
    </div>
  );
}

function TopList({ title, items }: {
  title: string; items: { k: string; n: number }[];
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <h3 className="text-sm font-semibold text-slate-700 mb-2">{title}</h3>
      {items.length === 0 ? (
        <div className="text-sm text-slate-400">None in window.</div>
      ) : (
        <ul className="space-y-1">
          {items.map((it) => (
            <li key={it.k} className="flex items-center justify-between gap-3 text-sm">
              <span className="font-mono text-xs truncate" title={it.k}>{it.k}</span>
              <span className="tabular-nums font-semibold text-slate-700 shrink-0">{it.n}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
