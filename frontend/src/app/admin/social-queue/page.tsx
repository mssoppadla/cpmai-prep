"use client";
/**
 * /admin/social-queue — feed of campaign runs ready for the admin to
 * post manually to social platforms.
 *
 * Default filter: status in (done, failed). Done = generated content
 * ready to copy; failed = needs review (see the error column).
 *
 * Per-row actions:
 *   * Copy content — clipboard the generated post
 *   * Mark posted — modal that asks platform + URL
 *   * Retry — re-execute the parent campaign synchronously
 *   * View raw — toggle the error/traceback for failed runs
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { admin, errMsg } from "@/lib/api";
import type { CampaignRunOut } from "@/types/api";


function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "short", timeStyle: "short",
  });
}

function statusBadge(status: string) {
  const map: Record<string, string> = {
    done:      "bg-emerald-50 text-emerald-700 border-emerald-200",
    failed:    "bg-rose-50 text-rose-700 border-rose-200",
    posted:    "bg-slate-100 text-slate-500 border-slate-200",
    running:   "bg-indigo-50 text-indigo-700 border-indigo-200",
    queued:    "bg-amber-50 text-amber-700 border-amber-200",
    cancelled: "bg-slate-100 text-slate-500 border-slate-200",
  };
  return (
    <span className={`px-2 py-0.5 text-xs rounded border ${map[status] ?? map.queued}`}>
      {status}
    </span>
  );
}


export default function SocialQueuePage() {
  const [rows, setRows] = useState<CampaignRunOut[] | null>(null);
  const [filter, setFilter] = useState<"" | "done" | "failed" | "posted">("");
  const [err, setErr] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [markPostedRun, setMarkPostedRun] = useState<CampaignRunOut | null>(null);
  const [expandError, setExpandError] = useState<number | null>(null);

  const reload = useCallback(async () => {
    setErr(null);
    try {
      setRows(await admin.social.listQueue(filter || undefined));
    } catch (e) { setErr(errMsg(e)); }
  }, [filter]);
  useEffect(() => { void reload(); }, [reload]);

  function copyContent(run: CampaignRunOut) {
    if (!run.generated_content) return;
    void navigator.clipboard.writeText(run.generated_content).then(() => {
      setCopiedId(run.id);
      setTimeout(() => setCopiedId((c) => (c === run.id ? null : c)), 1500);
    });
  }

  async function retryRun(runId: number) {
    setErr(null);
    try {
      await admin.social.retryRun(runId);
      await reload();
    } catch (e) { setErr(errMsg(e)); }
  }

  return (
    <div className="p-8 max-w-5xl">
      <header className="flex items-end justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Social queue</h1>
          <p className="text-slate-600 mt-1 text-sm">
            AI-generated content ready to post. Edit / schedule campaigns at{" "}
            <Link href="/admin/campaigns" className="text-indigo-600 hover:underline">
              /admin/campaigns
            </Link>.
          </p>
        </div>
        <select value={filter}
                onChange={(e) => setFilter(e.target.value as typeof filter)}
                className="px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white">
          <option value="">Pending (done + failed)</option>
          <option value="done">Done only</option>
          <option value="failed">Failed only</option>
          <option value="posted">Already posted</option>
        </select>
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      {rows === null ? (
        <div className="text-slate-500 text-sm">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-8 text-center text-slate-500">
          Queue is empty. Generated content from active campaigns will land here.
        </div>
      ) : (
        <ul className="space-y-3">
          {rows.map((run) => (
            <li key={run.id} className="bg-white border border-slate-200 rounded-xl p-4">
              <div className="flex items-start justify-between gap-4 mb-3">
                <div className="flex items-center gap-2">
                  {statusBadge(run.status)}
                  <span className="text-xs text-slate-500">
                    Campaign #{run.campaign_id} · {fmtDateTime(run.started_at)}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {run.status === "done" && (
                    <>
                      <button onClick={() => copyContent(run)}
                              className="px-3 py-1 text-xs border border-slate-300 rounded hover:bg-slate-50">
                        {copiedId === run.id ? "Copied ✓" : "Copy"}
                      </button>
                      <button onClick={() => setMarkPostedRun(run)}
                              className="px-3 py-1 text-xs bg-emerald-600 text-white rounded hover:bg-emerald-700">
                        Mark posted
                      </button>
                    </>
                  )}
                  {run.status === "failed" && (
                    <button onClick={() => retryRun(run.id)}
                            className="px-3 py-1 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700">
                      Retry
                    </button>
                  )}
                </div>
              </div>

              {run.generated_content && (
                <pre className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-sm text-slate-700 whitespace-pre-wrap font-sans">
{run.generated_content}
                </pre>
              )}

              {run.status === "failed" && run.error && (
                <div className="mt-2">
                  <button onClick={() => setExpandError((cur) => (cur === run.id ? null : run.id))}
                          className="text-xs text-rose-600 hover:underline">
                    {expandError === run.id ? "Hide" : "Show"} error
                  </button>
                  {expandError === run.id && (
                    <pre className="mt-2 bg-rose-50 border border-rose-200 rounded-lg p-3 text-xs text-rose-800 overflow-x-auto">
{run.error}
                    </pre>
                  )}
                </div>
              )}

              {run.posted_to_platforms.length > 0 && (
                <div className="mt-2 text-xs text-slate-500">
                  Posted to: {run.posted_to_platforms.map((p, i) => (
                    <span key={i} className="ml-1">
                      {p.url
                        ? <a href={p.url} target="_blank" rel="noopener noreferrer"
                             className="text-indigo-600 hover:underline">{p.platform}</a>
                        : <span>{p.platform}</span>}
                      {i < run.posted_to_platforms.length - 1 && ","}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {markPostedRun && (
        <MarkPostedModal
          run={markPostedRun}
          onCancel={() => setMarkPostedRun(null)}
          onSaved={async () => { setMarkPostedRun(null); await reload(); }}
        />
      )}
    </div>
  );
}


function MarkPostedModal({ run, onCancel, onSaved }: {
  run: CampaignRunOut;
  onCancel: () => void;
  onSaved: () => Promise<void> | void;
}) {
  const [platform, setPlatform] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    if (!platform.trim()) { setErr("Platform is required."); return; }
    setBusy(true); setErr(null);
    try {
      await admin.social.markPosted(run.id, {
        platform: platform.trim(),
        url: url.trim() || null,
      });
      await onSaved();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4"
         onClick={() => !busy && onCancel()}>
      <div onClick={(e) => e.stopPropagation()}
           className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
        <h3 className="font-semibold text-slate-900 mb-1">Mark as posted</h3>
        <p className="text-xs text-slate-500 mb-4">
          Record which platform you posted to + an optional permalink.
        </p>
        {err && (
          <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-2 rounded text-sm mb-3">
            {err}
          </div>
        )}
        <label className="block text-xs font-medium text-slate-700 mb-1">Platform *</label>
        <select value={platform} onChange={(e) => setPlatform(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white mb-3">
          <option value="">— Select —</option>
          <option value="linkedin">LinkedIn</option>
          <option value="twitter">X / Twitter</option>
          <option value="instagram">Instagram</option>
          <option value="youtube">YouTube</option>
          <option value="facebook">Facebook</option>
          <option value="threads">Threads</option>
          <option value="other">Other</option>
        </select>
        <label className="block text-xs font-medium text-slate-700 mb-1">URL (optional)</label>
        <input value={url} onChange={(e) => setUrl(e.target.value)}
               placeholder="https://linkedin.com/posts/..."
               className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm mb-4" />
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} disabled={busy}
                  className="px-3 py-2 text-sm border border-slate-300 rounded hover:bg-slate-50">
            Cancel
          </button>
          <button onClick={submit} disabled={busy || !platform}
                  className="px-3 py-2 text-sm bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-50">
            {busy ? "Saving…" : "Mark posted"}
          </button>
        </div>
      </div>
    </div>
  );
}
