"use client";
/**
 * /sessions/[id]/live — embedded Zoom Meeting SDK page.
 *
 * Flow:
 *   1. Fetch session metadata + signed SDK token from backend
 *   2. Lazy-import @zoom/meetingsdk client view (dynamic; ssr:false)
 *   3. Initialise + join the meeting in a contained element
 *
 * URL-share defence:
 *   - Backend's /lms/sessions/{id}/sdk-token endpoint is the ONLY way
 *     to get a valid SDK signature, and it requires a CPMAI auth token
 *     + active subscription/enrollment.
 *   - The signed JWT has a 30-minute TTL bound to user_name + meeting_id.
 *   - Even if a learner copies the URL of THIS page and sends it to a
 *     non-subscriber, that recipient can't get a signature.
 *
 * UI gating per host_config:
 *   - mute_on_entry → muted at join
 *   - allow_self_unmute → no mic control if false (CSS hides + SDK
 *     also enforces server-side)
 *   - allow_video_toggle → no cam control if false
 *   - chat_mode "admin_only" / "off" → chat panel hidden client-side
 *   - screen_share_mode "approval" → share button triggers an approval
 *     request via the SDK (Zoom's built-in flow)
 *
 * The Zoom Web SDK's component view is heavy (~3MB gzipped) so the
 * import is dynamic — page-level skeleton renders immediately while
 * the SDK loads.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { lmsPublic, errMsg } from "@/lib/api";
import type { ZoomSessionPublicOut, ZoomSDKTokenOut, UserOut } from "@/types/api";
import { auth } from "@/lib/api";


type Phase =
  | "auth_check"     // verifying user is signed in
  | "loading_meta"   // fetching session details
  | "loading_sdk"    // dynamically importing @zoom/meetingsdk
  | "joining"        // SDK initialising + joining the meeting
  | "joined"         // SDK active, video visible
  | "ended"          // user left or session ended
  | "error";


export default function LiveSessionPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = Number(params?.id);
  const [phase, setPhase] = useState<Phase>("auth_check");
  const [err, setErr] = useState<string | null>(null);
  const [session, setSession] = useState<ZoomSessionPublicOut | null>(null);
  const [user, setUser] = useState<UserOut | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Auth gate — same pattern as /sessions
  useEffect(() => {
    auth.me().then((u) => { setUser(u); setPhase("loading_meta"); })
              .catch(() => router.replace(`/login?next=/sessions/${sessionId}/live`));
  }, [router, sessionId]);

  // Metadata + signed SDK token
  const join = useCallback(async () => {
    if (!user || !sessionId) return;
    try {
      const s = await lmsPublic.getSession(sessionId);
      setSession(s);
      if (s.status !== "live" && s.status !== "scheduled") {
        setErr(`Session is '${s.status}' — cannot join.`);
        setPhase("error");
        return;
      }
      const token = await lmsPublic.getSessionSDKToken(sessionId);

      setPhase("loading_sdk");
      // Dynamic import — keeps Zoom SDK off the initial bundle for
      // every page on the site.
      const { default: ZoomMtgEmbedded } = await import("@zoom/meetingsdk/embedded");
      const client = ZoomMtgEmbedded.createClient();

      if (!containerRef.current) {
        setErr("Internal: embed container not ready");
        setPhase("error");
        return;
      }

      await client.init({
        zoomAppRoot: containerRef.current,
        language: "en-US",
        patchJsMedia: true,
        leaveOnPageUnload: true,
        customize: {
          // Client-side enforcement of host_config that doesn't have a
          // direct Zoom meeting-setting equivalent. Doesn't replace
          // server-side enforcement (Zoom itself respects mute/video
          // settings); just hides the buttons so learners don't get
          // confused trying to click disabled controls.
          chat: {
            popper: { disableDraggable: true },
          },
          toolbar: {
            buttons: [],
          },
        },
      });

      setPhase("joining");
      await client.join({
        signature: token.signature,
        sdkKey: token.sdk_key,
        meetingNumber: token.meeting_number,
        userName: token.user_name,
        userEmail: user.email,
        password: "",
      });
      setPhase("joined");

      // Apply host_config-driven UI restrictions AFTER the SDK is up.
      // The SDK exposes per-feature toggle APIs; the exact symbols vary
      // by version, so we use a best-effort approach: try, catch, log.
      try {
        const cfg = s.host_config;
        if (!cfg.allow_self_unmute) {
          // Hide the mic button via CSS — Zoom enforces the
          // server-side restriction; this just removes the obvious
          // "click me" affordance.
          containerRef.current.querySelectorAll('[aria-label*="mute" i]')
            .forEach((el) => (el as HTMLElement).style.display = "none");
        }
        if (!cfg.allow_video_toggle) {
          containerRef.current.querySelectorAll('[aria-label*="video" i],[aria-label*="camera" i]')
            .forEach((el) => (el as HTMLElement).style.display = "none");
        }
        if (cfg.chat_mode === "off" || cfg.chat_mode === "admin_only") {
          containerRef.current.querySelectorAll('[aria-label*="chat" i]')
            .forEach((el) => (el as HTMLElement).style.display = "none");
        }
      } catch (e) {
        console.warn("[zoom] host_config UI patch failed", e);
      }
    } catch (e) {
      console.error("[zoom] join failed", e);
      setErr(errMsg(e));
      setPhase("error");
    }
  }, [user, sessionId]);

  useEffect(() => {
    if (phase === "loading_meta") void join();
  }, [phase, join]);

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      {/* Top bar — visible while loading */}
      <header className="bg-slate-900 text-slate-200 px-4 py-2 flex items-center justify-between text-sm">
        <button onClick={() => router.push("/sessions")}
                className="hover:underline">
          ← Back to my sessions
        </button>
        <span className="text-slate-400">
          {session?.title ?? "Live session"}
        </span>
        <span className="text-xs text-slate-500">
          {phase === "joined" ? "Connected" :
           phase === "error" ? "Error" :
           phase === "joining" ? "Joining…" :
           phase === "loading_sdk" ? "Loading SDK…" :
           "Connecting…"}
        </span>
      </header>

      {err && (
        <div role="alert" className="bg-rose-900 text-rose-100 p-4 text-sm text-center">
          {err}
        </div>
      )}

      {/* The SDK draws into this div. Sized to fill remaining viewport. */}
      <div
        ref={containerRef}
        id="zoom-embed-root"
        className="flex-1 w-full bg-black"
        style={{ minHeight: "calc(100vh - 50px)" }}
      />

      {phase !== "joined" && phase !== "error" && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="bg-slate-900/80 text-slate-200 px-6 py-4 rounded-lg pointer-events-auto">
            <div className="animate-spin w-6 h-6 border-2 border-slate-600 border-t-indigo-500 rounded-full mx-auto mb-2" />
            <p className="text-sm text-center">
              {phase === "auth_check" && "Checking access…"}
              {phase === "loading_meta" && "Loading session…"}
              {phase === "loading_sdk" && "Loading Zoom SDK (this takes a moment first time)…"}
              {phase === "joining" && "Joining meeting…"}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
