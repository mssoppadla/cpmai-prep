"use client";
/**
 * "Listen as podcast" — an audio-only, continuous playthrough of a
 * course's video lessons, in chapter → lesson order.
 *
 * Design (per product decisions):
 *   - Audio source: the existing uploaded MP4s, played audio-only via a
 *     hidden <video> element (reliable MP4 decode + HTTP Range seeking
 *     through the token-gated /uploads handler). No transcoding.
 *   - External lessons (YouTube/Vimeo) are skipped, with a note — we
 *     can't stream their audio through our own player.
 *   - Resume: a dedicated server-side pointer (enrollment.podcast_*),
 *     so the learner picks up the exact track + position across devices.
 *   - Finishing a track auto-marks that lesson complete and advances.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { lmsPublic, errMsg } from "@/lib/api";
import { SiteHeader } from "@/components/layout/SiteHeader";
import type { CourseDetailPublicOut } from "@/types/api";


type Track = {
  lessonId: number;
  title: string;
  chapterTitle: string;
  label: string;       // "1.2"
  url: string;         // signed /uploads/...?token=
};

function isExternal(url: string | null | undefined): boolean {
  return !!url && /^https?:\/\//i.test(url) && !url.startsWith("/uploads/");
}

function fmt(t: number): string {
  if (!Number.isFinite(t) || t < 0) return "0:00";
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}


export default function CoursePodcastPage({
  params,
}: { params: { slug: string } }) {
  const router = useRouter();
  const audioRef = useRef<HTMLVideoElement | null>(null);
  // Set when we WANT the next-loaded track to start playing automatically
  // (auto-advance + explicit track clicks). Read in onLoadedMetadata/onCanPlay
  // so playback doesn't depend on React state having flushed yet.
  const wantPlayRef = useRef(false);

  const [detail, setDetail] = useState<CourseDetailPublicOut | null>(null);
  const [enrollmentId, setEnrollmentId] = useState<number | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [skippedCount, setSkippedCount] = useState(0);
  const [completed, setCompleted] = useState<Set<number>>(new Set());
  const [index, setIndex] = useState(0);
  const [resumeAt, setResumeAt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [curTime, setCurTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [rate, setRate] = useState(1);
  const [err, setErr] = useState<string | null>(null);

  // ----------------------------------------------------- load
  useEffect(() => {
    (async () => {
      try {
        const d = await lmsPublic.getCourse(params.slug);
        setDetail(d);
        if (!d.is_enrolled) return; // render guard below sends them back

        // Build the ordered audio queue (uploaded video lessons only).
        const queue: Track[] = [];
        let skipped = 0;
        d.chapters.forEach((ch, ci) => {
          ch.lessons.forEach((l, li) => {
            if (l.lesson_type !== "video") return;
            if (isExternal(l.video_url) || !l.video_url) { skipped++; return; }
            queue.push({
              lessonId: l.id, title: l.title, chapterTitle: ch.title,
              label: `${ci + 1}.${li + 1}`, url: l.video_url,
            });
          });
        });
        setTracks(queue);
        setSkippedCount(skipped);

        const mine = await lmsPublic.myEnrollments();
        const enr = mine.find((e) => e.course_id === d.course.id) ?? null;
        if (enr) {
          setEnrollmentId(enr.id);
          // Mark already-completed lessons from progress.
          const prog = await lmsPublic.listProgress(enr.id);
          setCompleted(new Set(prog.filter((p) => p.completed_at).map((p) => p.lesson_id)));
          // Resume from the saved pointer if it lands on a playable track.
          const at = enr.podcast_lesson_id != null
            ? queue.findIndex((t) => t.lessonId === enr.podcast_lesson_id) : -1;
          if (at >= 0) {
            setIndex(at);
            setResumeAt(enr.podcast_position_seconds ?? 0);
          }
        }
      } catch (e) { setErr(errMsg(e)); }
    })();
  }, [params.slug]);

  const current = tracks[index] ?? null;

  // ----------------------------------------------------- pointer persistence
  const savePointer = useCallback((seconds: number) => {
    if (enrollmentId == null || !current) return;
    lmsPublic.savePodcastPointer(enrollmentId, {
      lesson_id: current.lessonId,
      position_seconds: Math.max(0, Math.floor(seconds)),
    }).catch((e) => console.error("[podcast] save pointer", e));
  }, [enrollmentId, current]);

  // Flush on tab-hide / unmount so a quick pause-then-leave is captured.
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden" && audioRef.current) {
        savePointer(audioRef.current.currentTime);
      }
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      if (audioRef.current) savePointer(audioRef.current.currentTime);
    };
  }, [savePointer]);

  // Keep playback rate in sync.
  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = rate;
  }, [rate, index]);

  // Attempt playback, tolerating a rejected promise (autoplay block) by
  // reflecting the real paused state in the UI.
  function attemptPlay() {
    const a = audioRef.current;
    if (!a) return;
    const p = a.play();
    if (p && typeof p.then === "function") {
      p.then(() => setPlaying(true)).catch(() => setPlaying(false));
    } else {
      setPlaying(true);
    }
  }

  function playIndex(i: number, startAt = 0) {
    if (i < 0 || i >= tracks.length) return;
    wantPlayRef.current = true; // start the new track as soon as it loads
    setResumeAt(startAt);
    setIndex(i);
    setCurTime(startAt);
    setPlaying(true);
  }

  function togglePlay() {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) { attemptPlay(); }
    else { a.pause(); setPlaying(false); savePointer(a.currentTime); }
  }

  function markCompleteAndAdvance() {
    if (enrollmentId != null && current) {
      lmsPublic.updateProgress(enrollmentId, current.lessonId, { mark_completed: true })
        .then(() => setCompleted((s) => new Set(s).add(current.lessonId)))
        .catch((e) => console.error("[podcast] auto-complete", e));
    }
    if (index < tracks.length - 1) playIndex(index + 1, 0);
    else setPlaying(false);
  }

  // ----------------------------------------------------- render guards
  if (err) {
    return (
      <>
        <SiteHeader />
        <main className="min-h-screen max-w-2xl mx-auto px-6 py-10">
          <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">{err}</div>
        </main>
      </>
    );
  }
  if (!detail) {
    return (
      <>
        <SiteHeader />
        <main className="min-h-screen p-8 text-slate-500 text-sm">Loading podcast…</main>
      </>
    );
  }
  if (!detail.is_enrolled) {
    return (
      <>
        <SiteHeader />
        <main className="min-h-screen max-w-2xl mx-auto px-6 py-10">
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-6">
            <h2 className="font-semibold text-amber-900">Enrol to listen</h2>
            <p className="text-sm text-amber-800 mt-2">The course podcast is available to enrolled learners.</p>
            <Link href={`/courses/${params.slug}`}
                  className="inline-block mt-4 px-4 py-2 bg-amber-600 text-white text-sm font-medium rounded-lg hover:bg-amber-700">
              Back to course
            </Link>
          </div>
        </main>
      </>
    );
  }

  const progressPct = duration > 0 ? (curTime / duration) * 100 : 0;

  return (
    <>
      <SiteHeader />
      <main className="min-h-screen bg-slate-50">
        <div className="max-w-3xl mx-auto px-6 py-8">
          <Link href={`/courses/${params.slug}`} className="text-xs text-slate-500 hover:underline">
            ← {detail.course.title}
          </Link>
          <h1 className="text-2xl font-bold text-slate-900 mt-1 flex items-center gap-2">
            🎧 Course podcast
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Listen to every lesson back-to-back. We remember where you stop.
          </p>

          {tracks.length === 0 ? (
            <div className="mt-8 bg-white border border-slate-200 rounded-xl p-6 text-sm text-slate-600">
              No audio lessons available in this course yet.
            </div>
          ) : (
            <>
              {/* Now playing / player */}
              <section className="mt-6 bg-white border border-slate-200 rounded-2xl shadow-sm p-6">
                <div className="text-xs font-medium text-indigo-600 uppercase tracking-wide">
                  Now playing · {current?.label}
                </div>
                <h2 className="text-lg font-semibold text-slate-900 mt-1">{current?.title}</h2>
                <p className="text-xs text-slate-500">{current?.chapterTitle}</p>

                {/* Seek bar */}
                <div className="mt-5">
                  <input
                    type="range" min={0} max={duration || 0} step={1} value={curTime}
                    onChange={(e) => {
                      const a = audioRef.current; const v = Number(e.target.value);
                      if (a) a.currentTime = v;
                      setCurTime(v);
                    }}
                    onMouseUp={(e) => savePointer(Number((e.target as HTMLInputElement).value))}
                    className="w-full accent-indigo-600 cursor-pointer"
                    aria-label="Seek"
                  />
                  <div className="flex justify-between text-xs text-slate-500 tabular-nums mt-1">
                    <span>{fmt(curTime)}</span>
                    <span>{fmt(duration)}</span>
                  </div>
                </div>

                {/* Controls */}
                <div className="mt-4 flex items-center justify-center gap-6">
                  <button onClick={() => playIndex(index - 1, 0)} disabled={index === 0}
                          className="text-slate-600 hover:text-slate-900 disabled:opacity-30 text-xl" aria-label="Previous">
                    ⏮
                  </button>
                  <button onClick={togglePlay}
                          className="grid place-items-center w-14 h-14 rounded-full bg-indigo-600 text-white text-xl hover:bg-indigo-700 shadow-sm"
                          aria-label={playing ? "Pause" : "Play"}>
                    {playing ? "⏸" : "▶"}
                  </button>
                  <button onClick={() => playIndex(index + 1, 0)} disabled={index >= tracks.length - 1}
                          className="text-slate-600 hover:text-slate-900 disabled:opacity-30 text-xl" aria-label="Next">
                    ⏭
                  </button>
                </div>

                {/* Speed */}
                <div className="mt-4 flex items-center justify-center gap-2 text-xs">
                  <span className="text-slate-400">Speed</span>
                  {[1, 1.25, 1.5, 2].map((r) => (
                    <button key={r} onClick={() => setRate(r)}
                            className={`px-2 py-1 rounded-md font-medium ${
                              rate === r ? "bg-indigo-100 text-indigo-700" : "text-slate-500 hover:bg-slate-100"
                            }`}>
                      {r}×
                    </button>
                  ))}
                </div>

                <p className="mt-3 text-center text-[11px] text-slate-400">
                  Plays continuously — the next lesson starts automatically.
                </p>

                {/* Hidden media element — audio-only playback of the MP4. */}
                <video
                  ref={audioRef}
                  src={current?.url}
                  className="hidden"
                  preload="metadata"
                  onLoadedMetadata={(e) => {
                    const a = e.currentTarget;
                    a.playbackRate = rate;
                    setDuration(a.duration || 0);
                    if (resumeAt > 0 && Number.isFinite(a.duration) && resumeAt < a.duration - 1) {
                      a.currentTime = resumeAt;
                    }
                    // Auto-start when advancing/selecting a track (or if we were
                    // already playing). wantPlayRef avoids depending on React
                    // state having flushed for the new src yet.
                    if (wantPlayRef.current || playing) { wantPlayRef.current = false; attemptPlay(); }
                  }}
                  onCanPlay={(e) => {
                    // Fallback: some browsers are ready to play at canplay
                    // rather than loadedmetadata — honour a pending auto-start.
                    if (wantPlayRef.current && e.currentTarget.paused) {
                      wantPlayRef.current = false; attemptPlay();
                    }
                  }}
                  onTimeUpdate={(e) => {
                    const a = e.currentTarget;
                    setCurTime(a.currentTime);
                    if (Math.floor(a.currentTime) % 10 === 0) savePointer(a.currentTime);
                  }}
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                  onEnded={markCompleteAndAdvance}
                />
                {/* Progress sliver under the card */}
                <div className="mt-5 h-1 w-full rounded-full bg-slate-100 overflow-hidden">
                  <div className="h-full bg-indigo-600 transition-all" style={{ width: `${progressPct}%` }} />
                </div>
              </section>

              {/* Queue */}
              <section className="mt-6">
                <h3 className="text-sm font-semibold text-slate-900 mb-2">
                  Up next · {tracks.length} lessons
                </h3>
                <ol className="bg-white border border-slate-200 rounded-xl divide-y divide-slate-100 overflow-hidden">
                  {tracks.map((t, i) => {
                    const active = i === index;
                    const done = completed.has(t.lessonId);
                    return (
                      <li key={t.lessonId}>
                        <button onClick={() => playIndex(i, 0)}
                                className={`w-full text-left flex items-center gap-3 px-4 py-3 text-sm transition-colors ${
                                  active ? "bg-indigo-50" : "hover:bg-slate-50"
                                }`}>
                          <span className="w-5 shrink-0 text-center">
                            {active && playing ? <span className="text-indigo-600">▶</span>
                              : done ? <span className="text-emerald-500">✓</span>
                              : <span className="text-slate-400 text-xs">{i + 1}</span>}
                          </span>
                          <span className="flex-1 leading-snug">
                            <span className="text-slate-400 font-mono text-xs mr-1">{t.label}</span>
                            <span className={active ? "font-semibold text-indigo-900" : done ? "text-slate-500" : "text-slate-800"}>
                              {t.title}
                            </span>
                            <span className="block text-xs text-slate-400">{t.chapterTitle}</span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ol>
                {skippedCount > 0 && (
                  <p className="text-xs text-slate-400 mt-2">
                    {skippedCount} external {skippedCount === 1 ? "lesson is" : "lessons are"} not
                    available in the podcast (only uploaded videos can be played as audio).
                  </p>
                )}
              </section>
            </>
          )}
        </div>
      </main>
    </>
  );
}
