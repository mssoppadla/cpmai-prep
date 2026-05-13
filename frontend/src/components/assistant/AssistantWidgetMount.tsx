"use client";
/**
 * Client mount-point for the AssistantWidget.
 *
 * Lives in the root layout so the chat bubble shows on EVERY page —
 * landing, pricing, dashboard, exams, etc.
 *
 * Auth state is probed non-blocking in the background; the WIDGET
 * itself decides what to render based on whether `user` is null
 * (anonymous → "please sign in" CTA) or a real user (chat UI).
 * Either way the bubble is visible, so an anonymous visitor can
 * always tap it and immediately see how to access the AI tutor —
 * which is a stronger acquisition funnel than hiding the bubble
 * entirely (operator feedback: "the chat is the strongest CTA we
 * have; show it to everyone").
 */
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { auth } from "@/lib/api";
import type { UserOut } from "@/types/api";
import { AssistantWidget } from "./AssistantWidget";


export function AssistantWidgetMount() {
  const pathname = usePathname();
  const [user, setUser] = useState<UserOut | null>(null);
  const [probed, setProbed] = useState(false);

  // Re-probe auth on every route change.
  //
  // Why: this component lives in the ROOT layout, which Next.js's App
  // Router does NOT re-mount across client-side navigation. Without
  // this dependency, signing in via /login would store the JWT cookie
  // and router.push("/dashboard") — but our /users/me probe never
  // re-runs, so the widget keeps showing the anon "please sign in" CTA
  // until a full page reload. With `pathname` as a deps key, every
  // route change (login → dashboard, anywhere → anywhere, logout →
  // home) triggers a fresh probe. /users/me is cheap (one cached
  // user lookup, no DB hit on hot path).
  //
  // Trade-off: every client navigation costs one /users/me round-trip.
  // For typical session lengths (5–10 page views), that's 5–10 extra
  // requests per session — negligible vs. the UX win of the bubble
  // updating immediately after login/logout.
  useEffect(() => {
    let cancelled = false;
    auth.me()
      .then((u) => { if (!cancelled) setUser(u); })
      .catch(() => {
        // Anon or expired token — explicitly reset user state so a
        // logout (which navigates somewhere new) flips the widget back
        // to the anon CTA without waiting for a manual refresh.
        if (!cancelled) setUser(null);
      })
      .finally(() => { if (!cancelled) setProbed(true); });
    return () => { cancelled = true; };
  }, [pathname]);

  // Hold the bubble until we've at least probed once on first paint —
  // otherwise an already-signed-in user (returning visitor with a valid
  // JWT cookie) briefly sees the anon "please sign in" CTA before the
  // probe resolves. ~50–100ms on a warm connection. On subsequent
  // route changes `probed` stays true, so the bubble keeps rendering
  // continuously with the previous user state until the new probe lands.
  if (!probed) return null;
  return <AssistantWidget user={user} />;
}
