"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { admin, errMsg } from "@/lib/api";
import type { UserAdminOut, UserInsights } from "@/types/api";
import { linkedinHref } from "@/lib/linkedin";
import { buildJourneyRows, fmtDwell } from "@/lib/journey";
import { ActivityWindowFilter, toIsoUtc } from "@/components/admin/ActivityWindowFilter";

function fmtDuration(sec: number): string {
  if (!sec) return "0m";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}
function fmtDate(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  return isNaN(+d) ? "—" : d.toLocaleString();
}

/**
 * Admin "User Insights" — pick a user and see their exam results, time spent on
 * each part of the course, exam-attempt count, and recent activity in one view.
 * The picker list is queried live, so newly signed-up users appear as you search.
 */
export default function AdminUserInsightsPage() {
  const [q, setQ] = useState("");
  const [win, setWin] = useState({ from: "", to: "" });
  const [results, setResults] = useState<UserAdminOut[]>([]);
  const [selected, setSelected] = useState<UserAdminOut | null>(null);
  const [data, setData] = useState<UserInsights | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const list = await admin.users.list({
          q: q || undefined, limit: 20,
          active_from: toIsoUtc(win.from), active_to: toIsoUtc(win.to),
        });
        if (!cancel) setResults(list);
      } catch (e) { if (!cancel) setErr(errMsg(e)); }
    })();
    return () => { cancel = true; };
  }, [q, win.from, win.to]);

  async function pick(u: UserAdminOut) {
    setSelected(u); setData(null); setErr(null); setLoading(true);
    try { setData(await admin.users.insights(u.id)); }
    catch (e) { setErr(errMsg(e)); }
    finally { setLoading(false); }
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">User insights</h1>
        <p className="text-sm text-slate-500">
          Pick a user to see their exam results, time spent on each part of the course,
          attempt counts, and recent activity.
        </p>
      </div>

      {/* User picker — live search over the user list (reflects new signups). */}
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <label className="block text-sm font-medium text-slate-700 mb-1">Select a user</label>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search by email or name…"
          className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg
                     focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
        />
        <div className="mt-2">
          <ActivityWindowFilter from={win.from} to={win.to}
                                onChange={(from, to) => setWin({ from, to })} />
          <p className="mt-1 text-xs text-slate-400">
            Narrows the list to users who logged in or performed an activity in the window.
          </p>
        </div>
        <div className="mt-2 max-h-56 overflow-y-auto divide-y divide-slate-100 border border-slate-100 rounded-lg">
          {results.length === 0 && (
            <div className="px-3 py-3 text-sm text-slate-400">No users match.</div>
          )}
          {results.map((u) => (
            <button
              key={u.id}
              onClick={() => pick(u)}
              className={`w-full text-left px-3 py-2 hover:bg-slate-50 ${
                selected?.id === u.id ? "bg-indigo-50" : ""
              }`}
            >
              <div className="text-sm font-medium text-slate-900">
                {u.name || <span className="italic text-slate-400">no name</span>}
              </div>
              <div className="text-xs text-slate-500">{u.email}</div>
            </button>
          ))}
        </div>
      </div>

      {err && <div className="text-sm text-red-600">{err}</div>}
      {loading && <div className="text-sm text-slate-500">Loading insights…</div>}

      {data && !loading && (
        <div className="space-y-6">
          {/* Identity + contact */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="text-lg font-semibold text-slate-900">
              {data.user.name || data.user.email}
            </div>
            <div className="text-sm text-slate-500">{data.user.email}</div>
            {data.user.alt_emails?.map((e) => (
              <div key={e} className="text-xs text-slate-500" title="Also used this email on a landing form">
                alt: {e}
              </div>
            ))}
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
              {data.user.linkedin_id && (
                <span>in:{" "}
                  <a href={linkedinHref(data.user.linkedin_id)} target="_blank" rel="noopener noreferrer"
                     className="text-indigo-600 hover:underline">{data.user.linkedin_id}</a>
                </span>
              )}
              {data.user.whatsapp && <span>wa: {data.user.whatsapp}</span>}
              {data.user.last_login_at && <span>last login: {fmtDate(data.user.last_login_at)}</span>}
            </div>
          </div>

          {/* Exam summary */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <h2 className="text-sm font-semibold text-slate-700 mb-3">Exam attempts</h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
              <Stat label="Attempts" value={data.exam.attempt_count} />
              <Stat label="Passed" value={data.exam.pass_count} />
              <Stat label="Best score" value={data.exam.best_score != null ? `${data.exam.best_score}%` : "—"} />
              <Stat label="Avg score" value={data.exam.avg_score != null ? `${data.exam.avg_score}%` : "—"} />
            </div>
            {data.exam.attempts.length === 0 ? (
              <div className="text-sm text-slate-400">No submitted attempts yet.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-sm">
                  <thead className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider border-b border-slate-200">
                    <tr>
                      <th className="py-2 pr-3">Exam</th><th className="py-2 pr-3">Domain</th>
                      <th className="py-2 pr-3">Score</th><th className="py-2 pr-3">Result</th>
                      <th className="py-2 pr-3">Time</th><th className="py-2 pr-3">When</th>
                      <th className="py-2">Review</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.exam.attempts.map((a) => (
                      <tr key={a.id}>
                        <td className="py-2 pr-3">{a.exam_set || "—"}</td>
                        <td className="py-2 pr-3">{a.practice_domain || "full"}</td>
                        <td className="py-2 pr-3">{a.score != null ? `${a.score}%` : "—"}</td>
                        <td className="py-2 pr-3">
                          <span className={a.passed ? "text-emerald-700" : "text-slate-500"}>
                            {a.passed ? "Pass" : "Fail"}
                          </span>
                        </td>
                        <td className="py-2 pr-3">{a.time_taken_seconds ? fmtDuration(a.time_taken_seconds) : "—"}</td>
                        <td className="py-2 pr-3 text-slate-500">{fmtDate(a.submitted_at)}</td>
                        <td className="py-2">
                          <Link href={`/admin/user-insights/attempts/${a.id}`}
                                className="text-indigo-600 hover:underline">
                            View
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Course time-per-part */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <h2 className="text-sm font-semibold text-slate-700 mb-3">
              Course progress &amp; time per part
              <span className="ml-2 font-normal text-slate-400">· {data.quiz_attempts} quiz attempt(s)</span>
            </h2>
            {data.courses.length === 0 ? (
              <div className="text-sm text-slate-400">Not enrolled in any course.</div>
            ) : (
              <div className="space-y-4">
                {data.courses.map((c) => (
                  <div key={c.course_id} className="border border-slate-100 rounded-lg p-3">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="font-medium text-slate-900">{c.course_title}</div>
                      <div className="text-xs text-slate-500">
                        {c.progress_pct}% · {c.lessons_completed}/{c.lessons_total} lessons ·
                        {" "}{fmtDuration(c.total_watch_seconds)} watched
                        {c.completed && <span className="ml-1 text-emerald-700">· completed</span>}
                      </div>
                    </div>
                    <div className="h-1.5 bg-slate-100 rounded mt-2 overflow-hidden">
                      <div className="h-full bg-indigo-500" style={{ width: `${c.progress_pct}%` }} />
                    </div>
                    {c.chapters.length > 0 && (
                      <div className="mt-3 space-y-1">
                        {c.chapters.map((ch) => (
                          <div key={ch.chapter_id} className="flex items-center justify-between text-xs text-slate-600">
                            <span className="truncate pr-3">{ch.title}</span>
                            <span className="text-slate-500 whitespace-nowrap">
                              {ch.lessons_completed}/{ch.lessons_total} · {fmtDuration(ch.watch_seconds)}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Page journey — which pages, dwell time, where they went next */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <h2 className="text-sm font-semibold text-slate-700 mb-1">Page journey</h2>
            <p className="text-xs text-slate-400 mb-3">
              Pages this user visited, how long they actively stayed on each,
              and where they moved next. A divider marks a new browsing session;
              &ldquo;left&rdquo; means the tab was closed or the site abandoned.
            </p>
            {(data.page_journey ?? []).length === 0 ? (
              <div className="text-sm text-slate-400">No page visits tracked yet.</div>
            ) : (
              <div className="max-h-80 overflow-y-auto text-xs">
                {buildJourneyRows(data.page_journey).map((step, i) => (
                  <div key={i}>
                    {step.newSession && i > 0 && (
                      <div className="my-2 flex items-center gap-2 text-[10px] uppercase tracking-wide text-slate-400">
                        <span className="flex-1 border-t border-dashed border-slate-200" />
                        new session
                        <span className="flex-1 border-t border-dashed border-slate-200" />
                      </div>
                    )}
                    <div className="py-1.5 flex items-center gap-3">
                      <span className="text-slate-400 whitespace-nowrap w-32 flex-shrink-0">
                        {fmtDate(step.entered_at)}
                      </span>
                      <span className="font-mono text-slate-800 truncate">{step.path || "—"}</span>
                      <span className="text-indigo-600 font-medium whitespace-nowrap">
                        {fmtDwell(step.seconds)}
                      </span>
                      <span className="text-slate-400 flex-1 truncate text-right">
                        {step.next_path
                          ? <>→ <span className="font-mono text-slate-600">{step.next_path}</span></>
                          : <span className="italic">left / last page</span>}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Recent activity */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <h2 className="text-sm font-semibold text-slate-700 mb-3">Recent activity</h2>
            {data.activity.length === 0 ? (
              <div className="text-sm text-slate-400">No tracked activity.</div>
            ) : (
              <div className="max-h-72 overflow-y-auto divide-y divide-slate-100 text-xs">
                {data.activity.map((ev, i) => (
                  <div key={i} className="py-1.5 flex items-center justify-between gap-3">
                    <span className="font-mono text-slate-700">{ev.event}</span>
                    <span className="truncate text-slate-500 flex-1">{ev.path || ""}</span>
                    <span className="text-slate-400 whitespace-nowrap">
                      {ev.duration_ms ? `${Math.round(ev.duration_ms / 1000)}s · ` : ""}{fmtDate(ev.created_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-center">
      <div className="text-lg font-semibold text-slate-900">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}
