"use client";
/**
 * Client mount-point for the Visitor Insights tracker.
 *
 * Lives in the root layout so every route fires page.view +
 * page.heartbeat + page.exit events. The tracker itself is
 * idempotent — calling install() twice is a no-op — so a hot-reload
 * in dev doesn't double-install.
 *
 * ─── Route-template derivation (zero-maintenance) ──────────────────
 *
 * The dashboard needs to GROUP BY route TEMPLATE not raw URL — one
 * row for "/courses/[slug]" not 200 rows for each course slug. Two
 * possible approaches:
 *
 *   A. Server-side regex registry (what we did first) — every new
 *      dynamic route requires hand-editing a list. Drifts on every
 *      `/something/[param]` page added.
 *
 *   B. Client-side derivation via useParams() — Next.js already
 *      knows every dynamic segment because it parsed the URL against
 *      the route file tree at build time. We just ask it.
 *
 * We use (B). For any route ``/courses/cpmai-foundation-2026/lessons/42``
 * with params ``{ slug: "cpmai-foundation-2026", lid: "42" }`` we walk
 * the path segments, replace each one whose value matches a param
 * value with ``[paramName]``, and ship the result as the canonical
 * path. No registry, no drift — adding a new ``app/instructors/[name]``
 * route auto-rolls-up the day it's deployed.
 *
 * The server-side normalizer (path_normaliser.py) is kept as a fallback
 * for backend-emitted events (auth.signup, payment.success, etc.) that
 * don't know their route template.
 *
 * ─── Route-change capture pattern ──────────────────────────────────
 *
 *   * Next.js App Router doesn't fire a built-in "route changed"
 *     event — it just rerenders. We use the usePathname() hook to
 *     detect pathname transitions in a useEffect, then call
 *     trackPageView() with the derived template.
 *   * On the very first render usePathname() returns the initial
 *     path, so the first page.view fires as expected.
 *
 * Why a separate component instead of dropping the install() call in
 * RootLayout: RootLayout is a server component. The tracker is browser
 * code (window / document / IntersectionObserver). Wrapping in a
 * "use client" boundary is the cleanest way to keep the layout
 * server-rendered while still booting the tracker.
 */
import { useEffect } from "react";
import { useParams, usePathname, useSearchParams } from "next/navigation";
import { install, trackPageView } from "@/lib/tracker";


/**
 * Convert a raw pathname + Next.js route params into the route
 * template. ``/courses/cpmai-2026/lessons/42`` + ``{slug:"cpmai-2026",
 * lid:"42"}`` → ``/courses/[slug]/lessons/[lid]``.
 *
 * Algorithm:
 *   1. Build a Map keyed by param VALUE → param NAME (reverse lookup).
 *      For catch-all params (`[...slug]`) the value is an array; we
 *      register each element.
 *   2. Walk the path segments. If a segment matches a param value
 *      exactly, replace with ``[paramName]``; else keep as-is.
 *
 * Exported for unit testing.
 */
export function deriveRouteTemplate(
  pathname: string,
  params: Record<string, string | string[]> | null,
): string {
  if (!pathname) return "/";
  if (!params || Object.keys(params).length === 0) return pathname;

  // Reverse map: value → param name. Multiple params shouldn't share
  // a value in practice, but if they did we'd pick the last one which
  // is fine for normalisation purposes.
  const valueToName = new Map<string, string>();
  for (const [name, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      // Catch-all routes: each segment of the array matches a path part
      for (const v of value) valueToName.set(v, name);
    } else if (typeof value === "string") {
      valueToName.set(value, name);
    }
  }

  const segments = pathname.split("/");
  const out: string[] = segments.map((seg) => {
    if (!seg) return seg;   // preserve leading/trailing empty for join
    const name = valueToName.get(seg);
    return name ? `[${name}]` : seg;
  });
  return out.join("/") || "/";
}


export function TrackerMount() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const params = useParams();

  // One-time install on mount. install() is internally idempotent and
  // SSR-safe so calling it from a "use client" component is fine even
  // if Next.js double-invokes effects in dev strict mode.
  useEffect(() => {
    install();
  }, []);

  // Fire page.view on every pathname OR search-params change. We
  // include searchParams because a UTM-tagged URL on the same path
  // (?utm_source=newsletter) is a genuinely new attribution event,
  // not a duplicate page view.
  useEffect(() => {
    if (!pathname) return;
    // Derive the route template (e.g. /courses/[slug]) so the
    // dashboard GROUP BY is correct regardless of which slug the
    // visitor landed on. No server-side registry maintenance needed.
    const template = deriveRouteTemplate(
      pathname,
      params as Record<string, string | string[]> | null,
    );
    trackPageView(template);
    // searchParams.toString() rather than the object itself so the
    // effect deps stay primitive and React's shallow-equal works.
  }, [pathname, searchParams?.toString(), params]);

  return null;
}
