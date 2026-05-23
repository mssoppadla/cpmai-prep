"use client";
/**
 * /sessions/[id]/recording — playback for a finished Zoom session.
 *
 * Fetches a 1-hour signed URL from /lms/sessions/{id}/recording (the
 * backend audit-logs each issuance). The MP4 lives on the backend's
 * /uploads volume; we use absoluteUploadUrl() to point the HTML5
 * <video> at the right origin.
 *
 * UX:
 *   * Auth-gate (same pattern as /sessions/[id]/live)
 *   * Standard <video controls> — native browser player; supports
 *     keyboard shortcuts, full-screen, picture-in-picture
 *   * Subtle "Issued URL expires at <time>" hint so the learner
 *     knows to refresh if they leave the page open overnight
 *   * No download attribute on the video element — discourages the
 *     trivial "save video as..." path. (Determined users can still
 *     scrape it; this is friction, not security.)
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { auth, lmsPublic, absoluteUploadUrl, errMsg } from "@/lib/api";
import type {
  SignedRecordingPlaybackOut, ZoomSessionPublicOut, UserOut,
} from "@/types/api";


function fmtDuration(seconds: number | null): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric", minute: "2-digit",
  });
}


export default function RecordingPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = Number(params?.id);
  const [me, setMe] = useState<UserOut | null | undefined>(undefined);
  const [session, setSession] = useState<ZoomSessionPublicOut | null>(null);
  const [playback, setPlayback] = useState<SignedRecordingPlaybackOut | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Auth gate
  useEffect(() => {
    auth.me().then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(() => {
    if (me === null) router.replace(`/login?next=/sessions/${sessionId}/recording`);
  }, [me, router, sessionId]);

  // Load metadata + signed URL
  useEffect(() => {
    if (!me || !sessionId) return;
    (async () => {
      try {
        setSession(await lmsPublic.getSession(sessionId));
        setPlayback(await lmsPublic.getSessionRecording(sessionId));
      } catch (e) {
        setErr(errMsg(e));
      }
    })();
  }, [me, sessionId]);

  if (me === undefined) {
    return (
      <>
        <SiteHeader />
        <main className="p-8 text-slate-500">Loading…</main>
        <SiteFooter />
      </>
    );
  }

  return (
    <>
      <SiteHeader />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 py-8">
        <Link href="/sessions"
              className="text-sm text-indigo-600 hover:underline">
          ← Back to my sessions
        </Link>

        <header className="mt-3 mb-5">
          <h1 className="text-2xl font-bold text-slate-900">
            {session?.title ?? "Session recording"}
          </h1>
          {session && (
            <p className="text-sm text-slate-500 mt-1">
              Originally aired {new Date(session.scheduled_at).toLocaleString()} · {session.duration_minutes} min
            </p>
          )}
        </header>

        {err && (
          <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg text-sm mb-4">
            {err}
          </div>
        )}

        {!playback ? (
          <div className="bg-white border border-slate-200 rounded-xl p-6 text-slate-500">
            Loading playback…
          </div>
        ) : (
          <>
            <div className="bg-black rounded-xl overflow-hidden mb-3">
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <video
                controls
                controlsList="nodownload"
                disablePictureInPicture={false}
                preload="metadata"
                src={absoluteUploadUrl(playback.url)}
                className="w-full aspect-video"
              />
            </div>
            <div className="flex justify-between text-xs text-slate-500">
              <span>Duration: {fmtDuration(playback.duration_seconds)}</span>
              <span>Playback URL expires at {fmtTime(playback.expires_at)}</span>
            </div>
          </>
        )}
      </main>
      <SiteFooter />
    </>
  );
}
