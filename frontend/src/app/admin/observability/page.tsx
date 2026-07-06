"use client";
/**
 * /admin/observability — VPS health surface.
 *
 * Currently shows the disk gauge + per-application breakdown + a
 * list of "reclaim" hints (operator-side SSH commands). The backend
 * runs in a docker container and can't shell out to host commands,
 * so destructive cleanup stays a manual operator action — but every
 * suggested command is co-located with its rationale so it's a
 * single copy-paste from this page.
 *
 * Future tabs to add to this page (per docs/pr7-followups.md E2):
 *   • Per-service log tail
 *   • Container restart counts (docker events bridge)
 *   • Cron-job health (geoip refresh, fx refresh)
 */
import { useEffect, useState, useCallback } from "react";
import { admin, errMsg } from "@/lib/api";
import type { DiskUsageOut } from "@/types/api";


/** Format bytes → GB / MB / KB. */
function fmtBytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}


export default function ObservabilityPage() {
  const [data, setData] = useState<DiskUsageOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setErr(null);
    try {
      setData(await admin.observability.disk());
    } catch (e) {
      setErr(errMsg(e));
    }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  function copyCommand(id: string, command: string) {
    void navigator.clipboard.writeText(command).then(() => {
      setCopiedId(id);
      setTimeout(() => setCopiedId((cur) => (cur === id ? null : cur)), 1500);
    });
  }

  if (err) {
    return (
      <div className="p-8 max-w-4xl">
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">
          {err}
        </div>
      </div>
    );
  }
  if (!data) {
    return <div className="p-8 text-slate-500">Loading disk usage…</div>;
  }

  const fs = data.filesystem;
  const app = data.application;
  const appPercentOfFs = fs.total_bytes > 0
    ? (app.total_bytes / fs.total_bytes) * 100
    : 0;

  return (
    <div className="p-8 max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">VPS observability</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Disk usage on the host + items the operator can reclaim safely.
        </p>
      </header>

      {/* ──────────────────── Disk gauge ──────────────────── */}
      <section className="bg-white border border-slate-200 rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-slate-900">Filesystem</h2>
          <button onClick={reload}
                  className="text-xs px-3 py-1 border border-slate-300 rounded hover:bg-slate-50">
            Refresh
          </button>
        </div>

        <div className="mb-4">
          <div className="flex justify-between text-sm mb-1">
            <span className="text-slate-700 font-mono text-xs">{fs.path}</span>
            <span className="text-slate-900 font-medium">
              {fmtBytes(fs.used_bytes)} / {fmtBytes(fs.total_bytes)} ({fs.used_percent}%)
            </span>
          </div>
          {/* Gauge bar */}
          <div className="h-4 w-full bg-slate-100 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all ${
                fs.used_percent >= 90
                  ? "bg-rose-500"
                  : fs.used_percent >= 75
                    ? "bg-amber-500"
                    : "bg-emerald-500"
              }`}
              style={{ width: `${fs.used_percent}%` }}
            />
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {fmtBytes(fs.free_bytes)} free
          </div>
        </div>

        {/* Application breakdown */}
        <h3 className="text-sm font-semibold text-slate-700 mt-6 mb-2">
          This application&apos;s share
        </h3>
        {/* overflow-x-auto: long mono paths must scroll on phones, not
            clip — see admin-tables-mobile-scroll.test.ts */}
        <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <tbody className="divide-y divide-slate-100">
            <tr>
              <td className="py-2 text-slate-700">Uploads volume</td>
              <td className="py-2 text-slate-500 text-xs font-mono">{app.uploads_volume.path}</td>
              <td className="py-2 text-right font-medium text-slate-900">{fmtBytes(app.uploads_volume.size_bytes)}</td>
            </tr>
            <tr>
              <td className="py-2 text-slate-700">Backend logs</td>
              <td className="py-2 text-slate-500 text-xs font-mono">{app.logs_dir.path}</td>
              <td className="py-2 text-right font-medium text-slate-900">{fmtBytes(app.logs_dir.size_bytes)}</td>
            </tr>
            <tr className="font-semibold">
              <td className="py-2 text-slate-900">App total (visible from container)</td>
              <td className="py-2"></td>
              <td className="py-2 text-right text-slate-900">
                {fmtBytes(app.total_bytes)} ({appPercentOfFs.toFixed(2)}% of disk)
              </td>
            </tr>
          </tbody>
        </table>
        </div>
        <p className="text-xs text-slate-500 mt-3">
          Backend can&apos;t see the host directly (pg volume, docker images, system logs). Run the
          reclaim commands below via SSH to see the rest.
        </p>
      </section>

      {/* ──────────────────── Reclaimable items ──────────────────── */}
      <section className="bg-white border border-slate-200 rounded-xl p-6">
        <h2 className="font-semibold text-slate-900 mb-1">Items you can delete safely</h2>
        <p className="text-xs text-slate-500 mb-4">
          Operator-side cleanup. Copy the command, SSH to the VPS, paste, run. The deploy
          script already cleans some of these automatically — these are the manual catchups.
        </p>
        <ul className="space-y-4">
          {data.reclaimable.map((r) => (
            <li key={r.id} className="border border-slate-200 rounded-lg p-4">
              <div className="flex items-start justify-between gap-3 mb-2">
                <div>
                  <div className="font-medium text-slate-900 text-sm flex items-center gap-2">
                    {r.label}
                    {r.safety === "safe" ? (
                      <span className="px-2 py-0.5 text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 rounded">safe</span>
                    ) : (
                      <span className="px-2 py-0.5 text-xs bg-amber-50 text-amber-700 border border-amber-200 rounded">review first</span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500 mt-0.5 font-mono">{r.where}</div>
                </div>
                <button
                  onClick={() => copyCommand(r.id, r.command)}
                  className="text-xs px-3 py-1 border border-slate-300 rounded hover:bg-slate-50 flex-shrink-0"
                >
                  {copiedId === r.id ? "Copied ✓" : "Copy command"}
                </button>
              </div>
              <pre className="bg-slate-900 text-slate-100 px-3 py-2 rounded text-xs overflow-x-auto">
{r.command}
              </pre>
              {r.notes && (
                <p className="text-xs text-slate-500 mt-2">{r.notes}</p>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
