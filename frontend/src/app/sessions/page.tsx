"use client";
/**
 * /sessions — the user's "My Sessions" page.
 *
 * Shows upcoming + currently-live Zoom sessions the user can join.
 * Past sessions are hidden by default (toggleable). Subscription /
 * enrollment gating is enforced server-side; this page just renders
 * what /lms/sessions returns for the current user.
 *
 * Status-driven CTA:
 *   * "live"       → big green "Join live now" button → /sessions/[id]/live
 *   * "scheduled"  → countdown + disabled button (live ~5 min before start)
 *   * "ended"      → "Recording" button if a recording exists (Z-B3 wires this)
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { auth, lmsPublic, errMsg } from "@/lib/api";
import type { ZoomSessionPublicOut, UserOut } from "@/types/api";


function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

function statusPill(status: string) {
  const map: Record<string, string> = {
    scheduled: "bg-indigo-50 text-indigo-700 border-indigo-200",
    live:      "bg-emerald-50 text-emerald-700 border-emerald-200 animate-pulse",
    ended:     "bg-slate-100 text-slate-500 border-slate-200",
  };
  return (
    <span className={`px-2 py-0.5 text-xs rounded-full border ${map[status] ?? map.scheduled}`}>
      {status === "live" ? "● Live now" : status}
    </span>
  );
}

/** A session becomes "joinable" 5 min before scheduled_at. Before that
 *  we render the button disabled with a countdown so the page doesn't
 *  silently let people in early. */
function isJoinableNow(s: ZoomSessionPublicOut): boolean {
  if (s.status === "live") return true;
  if (s.status !== "scheduled") return false;
  const start = new Date(s.scheduled_at).getTime();
  return Date.now() >= start - 5 * 60 * 1000;
}


export default function MySessionsPage() {
  const router = useRouter();
  const [sessions, setSessions] = useState<ZoomSessionPublicOut[] | null>(null);
  const [me, setMe] = useState<UserOut | null | undefined>(undefined);
  const [includePast, setIncludePast] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    auth.me().then(setMe).catch(() => setMe(null));
  }, []);

  const reload = useCallback(async () => {
    setErr(null);
    try {
      setSessions(await lmsPublic.listSessions({ include_past: includePast }));
    } catch (e) {
      setErr(errMsg(e));
    }
  }, [includePast]);
  useEffect(() => { if (me) void reload(); }, [me, reload]);

  if (me === undefined) {
    return (
      <>
        <SiteHeader />
        <main className="p-8 text-slate-500">Loading…</main>
        <SiteFooter />
      </>
    );
  }
  if (me === null) {
    return (
      <>
        <SiteHeader />
        <main className="max-w-3xl mx-auto p-8">
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Live Sessions</h1>
          <p className="text-slate-600 mb-4">
            Sign in to see scheduled sessions and join live classes.
          </p>
          <button onClick={() => router.push("/login?next=/sessions")}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700">
            Sign in
          </button>
        </main>
        <SiteFooter />
      </>
    );
  }

  return (
    <>
      <SiteHeader />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 py-10">
        <header className="flex items-end justify-between mb-6 gap-3">
          <div>
            <h1 className="text-3xl font-bold text-slate-900">My Sessions</h1>
            <p className="text-slate-600 mt-1 text-sm">
              Live Zoom sessions from courses you&apos;re enrolled in or your active subscription.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={includePast}
                   onChange={(e) => setIncludePast(e.target.checked)} />
            Show past sessions
          </label>
        </header>

        {err && (
          <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
            {err}
          </div>
        )}

        {sessions === null ? (
          <div className="text-slate-500 text-sm">Loading…</div>
        ) : sessions.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-xl p-8 text-center">
            <p className="text-slate-700 font-medium">No sessions {includePast ? "yet" : "scheduled"}.</p>
            <p className="text-slate-500 text-sm mt-1">
              Enroll in a course or activate a subscription to see scheduled live sessions here.
            </p>
            <Link href="/courses"
                  className="inline-block mt-4 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
              Browse courses
            </Link>
          </div>
        ) : (
          <ul className="space-y-3">
            {sessions.map((s) => (
              <li key={s.id} className="bg-white border border-slate-200 rounded-xl p-4 sm:p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      {statusPill(s.status)}
                      <span className="text-xs text-slate-500">{s.duration_minutes}m</span>
                    </div>
                    <h2 className="font-semibold text-slate-900 truncate">{s.title}</h2>
                    <p className="text-sm text-slate-500 mt-0.5">{fmtDateTime(s.scheduled_at)}</p>
                    {s.description && (
                      <p className="text-sm text-slate-600 mt-2 line-clamp-2">{s.description}</p>
                    )}
                  </div>
                  <div className="flex-shrink-0">
                    {s.status === "live" && (
                      <Link href={`/sessions/${s.id}/live`}
                            className="px-4 py-2 bg-emerald-600 text-white text-sm font-semibold rounded-lg hover:bg-emerald-700">
                        Join live now
                      </Link>
                    )}
                    {s.status === "scheduled" && (
                      isJoinableNow(s) ? (
                        <Link href={`/sessions/${s.id}/live`}
                              className="px-4 py-2 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700">
                          Join early
                        </Link>
                      ) : (
                        <button disabled
                                className="px-4 py-2 bg-slate-100 text-slate-400 text-sm font-medium rounded-lg cursor-not-allowed">
                          Starts {fmtDateTime(s.scheduled_at)}
                        </button>
                      )
                    )}
                    {s.status === "ended" && (
                      <Link href={`/sessions/${s.id}/recording`}
                            className="px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50">
                        Recording
                      </Link>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>
      <SiteFooter />
    </>
  );
}
