/**
 * Server-side fetch helpers for public pages.
 *
 * Why this exists: the SEO-critical pages (/, /pricing, /courses,
 * /exams) render their content in the initial HTML by fetching public
 * backend endpoints from the SERVER component. Crawlers and ad-platform
 * landing-page reviewers never execute our client JS, so anything not
 * in this first response is invisible to them.
 *
 * Caching: default revalidate is 60s (ISR) — pages are served from the
 * Next cache and refreshed in the background, so ad-click TTFB doesn't
 * wait on the backend. Admin content edits appear within a minute
 * (trade-off approved 2026-07-13). Pass revalidate=0 for request-time
 * freshness where a page truly needs it.
 */
export const API =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export const DEFAULT_REVALIDATE_S = 60;

export async function fetchJson<T>(
  path: string,
  fallback: T,
  revalidate: number = DEFAULT_REVALIDATE_S,
): Promise<T> {
  try {
    const r = await fetch(`${API}${path}`,
      revalidate > 0 ? { next: { revalidate } } : { cache: "no-store" });
    if (!r.ok) return fallback;
    const data = await r.json();
    // Defensive: merge/shape-check is the caller's job; only guard the
    // "API returned something unparseable as the expected container".
    return (data ?? fallback) as T;
  } catch {
    return fallback;
  }
}
