/**
 * Visitor Insights tracker (client-side).
 *
 * Captures page views, active time on page, scroll depth, and
 * data-track="cta:<name>" clicks. Batches events for 5 seconds then
 * POSTs to /api/v1/track. On page hide / route change we flush via
 * navigator.sendBeacon so the last events make it even if the visitor
 * navigates away mid-batch.
 *
 * Design choices:
 *
 *   * Single instance per tab. The TrackerMount component (mounted in
 *     the root layout) calls install() once on mount. Hot-reload
 *     duplicates are guarded by a window-scoped flag.
 *
 *   * Session id is a UUID stored in sessionStorage. It dies when the
 *     tab closes — which matches the analytics intuition of "a session"
 *     better than a long-lived cookie would.
 *
 *   * Heartbeat fires every 15s ONLY while the tab is visible (Page
 *     Visibility API). Background tabs don't accumulate fake active
 *     time. This is what makes "avg time on page" actually meaningful.
 *
 *   * Scroll depth is sampled with IntersectionObserver against four
 *     sentinel divs the tracker injects (25/50/75/100% of document).
 *     Each bucket fires at most once per page view.
 *
 *   * CTA tracking uses event delegation on `document` — find any
 *     element with `data-track="cta:<name>"` on the click bubble path.
 *     No per-button wiring needed.
 *
 *   * sendBeacon on pagehide. fetch() is unreliable during navigation;
 *     sendBeacon is the only API that guarantees the request leaves.
 *     Falls back to fetch with keepalive if sendBeacon is missing.
 *
 *   * Best-effort, never blocks the visitor. Every error is swallowed
 *     with a single console.warn so devs can see it but visitors don't.
 *
 *   * Honours Do-Not-Track. If `navigator.doNotTrack === "1"` we
 *     install nothing — no events, no listeners.
 *
 * The Next.js App Router doesn't fire a built-in "route changed"
 * event, so we use the usePathname() hook in the React mount
 * component to emit page.view + page.exit at the right moments.
 */

type EventName =
  | "page.view"
  | "page.heartbeat"
  | "page.exit"
  | "scroll.depth"
  | "cta.click"
  | "session.start"
  | "session.end";

interface TrackEvent {
  event: EventName;
  event_id: string;
  session_id: string;
  path: string;
  referrer?: string;
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  duration_ms?: number;
  scroll_pct?: number;
  metadata?: Record<string, unknown>;
}

const BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const TRACK_URL = BASE + "/track";

const SESSION_KEY = "vi_session_id";
const BATCH_MAX = 25;
const FLUSH_INTERVAL_MS = 5_000;
const HEARTBEAT_INTERVAL_MS = 15_000;

const SCROLL_BUCKETS = [25, 50, 75, 100] as const;

// ---- module-scoped state ----

let installed = false;
let queue: TrackEvent[] = [];
let flushTimer: ReturnType<typeof setInterval> | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;

// Per-page-view state — reset on every page.view emit
let currentPath: string | null = null;
let currentPageStartMs = 0;
let activeTimeMs = 0;        // accumulated active ms on the current page
let lastVisibleAtMs = 0;     // timestamp of last visibility transition to visible
let scrolledBuckets = new Set<number>();
let scrollObserver: IntersectionObserver | null = null;
let utmsForSession: Pick<TrackEvent, "utm_source" | "utm_medium" | "utm_campaign"> = {};

// ---- helpers ----

function uuid(): string {
  // crypto.randomUUID is supported in all modern browsers; fall back
  // to a Math.random-based v4 if a very old browser slips through.
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function getOrCreateSessionId(): string {
  try {
    let id = sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      id = uuid();
      sessionStorage.setItem(SESSION_KEY, id);
      // First visit in this tab — fire session.start so the dashboard
      // can compute session counts independently of page.view dedup.
      enqueue({
        event: "session.start",
        event_id: uuid(),
        session_id: id,
        path: window.location.pathname || "/",
      });
    }
    return id;
  } catch {
    // sessionStorage can throw in private mode on some browsers.
    // Fall back to an in-memory id (session degrades to per-page).
    return uuid();
  }
}

function captureUtms(searchParams: URLSearchParams): void {
  // Capture UTMs the first time we see them this session, then keep
  // shipping them on every event — attribution analytics needs to
  // know "which campaign brought this visitor" for every action they
  // took, not just the landing page view.
  const src = searchParams.get("utm_source");
  const med = searchParams.get("utm_medium");
  const cmp = searchParams.get("utm_campaign");
  if (src || med || cmp) {
    utmsForSession = {
      utm_source: src ?? undefined,
      utm_medium: med ?? undefined,
      utm_campaign: cmp ?? undefined,
    };
  }
}

/** The session's captured UTM parameters — used by checkout to stamp
 *  ad-campaign attribution onto the payment row. */
export function getSessionUtms(): {
  utm_source?: string; utm_medium?: string; utm_campaign?: string;
} {
  return { ...utmsForSession };
}

function enqueue(ev: TrackEvent): void {
  // Always merge in session-level UTMs so every event carries
  // attribution context.
  queue.push({ ...utmsForSession, ...ev });
  if (queue.length >= BATCH_MAX) {
    void flush();
  }
}

/**
 * Bearer header for /track flushes. When the visitor is signed in the
 * backend stamps user_id onto every event row, which is what makes the
 * admin User Insights page journey attribute page views to the user.
 * Same storage key as lib/api.ts. Expired/invalid tokens are harmless:
 * /track's get_optional_user degrades to anonymous, never rejects.
 * sendBeacon flushes (tab close) can't carry headers — those events
 * stay anonymous and are joined server-side via anon_id/session_id.
 */
export function trackAuthHeaders(): Record<string, string> {
  try {
    const t = typeof window !== "undefined"
      ? window.localStorage.getItem("cpmai.access") : null;
    return t ? { Authorization: `Bearer ${t}` } : {};
  } catch {
    return {};   // storage blocked (private mode / hardened browser)
  }
}

async function flush(): Promise<void> {
  if (queue.length === 0) return;
  const batch = queue;
  queue = [];
  const payload = JSON.stringify({
    events: batch,
    sent_at: new Date().toISOString(),
  });
  try {
    // Prefer keepalive fetch (allows JSON body + bearer token).
    // sendBeacon is used specifically for pagehide where keepalive
    // fetch is also unreliable in older Safari.
    await fetch(TRACK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...trackAuthHeaders() },
      body: payload,
      keepalive: true,
      credentials: "include",  // ship the anon_id cookie
    });
  } catch (e) {
    // Don't requeue — back-pressure would balloon memory under
    // network outage. The dashboard tolerates small data loss.
    // eslint-disable-next-line no-console
    console.warn("[tracker] flush failed", e);
  }
}

function flushSync(): void {
  // Synchronous flush for pagehide / beforeunload. sendBeacon is the
  // only API the browser guarantees to send before unload.
  if (queue.length === 0) return;
  const batch = queue;
  queue = [];
  const payload = JSON.stringify({
    events: batch,
    sent_at: new Date().toISOString(),
  });
  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([payload], { type: "application/json" });
      navigator.sendBeacon(TRACK_URL, blob);
      return;
    }
    // Fallback for browsers without sendBeacon. keepalive fetch can
    // still squeak through in most modern setups.
    void fetch(TRACK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...trackAuthHeaders() },
      body: payload,
      keepalive: true,
      credentials: "include",
    });
  } catch {
    // Swallow — we tried.
  }
}

function onVisibilityChange(): void {
  if (document.visibilityState === "visible") {
    lastVisibleAtMs = Date.now();
  } else {
    // Tab went background — accumulate the active span we just left.
    if (lastVisibleAtMs > 0) {
      activeTimeMs += Date.now() - lastVisibleAtMs;
      lastVisibleAtMs = 0;
    }
  }
}

function currentActiveMs(): number {
  // Active time = accumulated + (now - lastVisibleAt if currently visible).
  let ms = activeTimeMs;
  if (lastVisibleAtMs > 0 && document.visibilityState === "visible") {
    ms += Date.now() - lastVisibleAtMs;
  }
  return ms;
}

function installScrollWatchers(sessionId: string): void {
  // Tear down previous observer (page changed)
  if (scrollObserver) {
    scrollObserver.disconnect();
    scrollObserver = null;
  }
  scrolledBuckets = new Set();

  // Inject four invisible sentinels at 25/50/75/100% of the document
  // body height. IntersectionObserver tells us when they enter the
  // viewport — that's when we know the user scrolled past that mark.
  const sentinels: HTMLElement[] = [];
  for (const pct of SCROLL_BUCKETS) {
    const el = document.createElement("div");
    el.style.position = "absolute";
    el.style.left = "0";
    el.style.width = "1px";
    el.style.height = "1px";
    el.style.pointerEvents = "none";
    el.style.opacity = "0";
    el.dataset.viScrollBucket = String(pct);
    // Position relative to body height — set lazily because layout
    // may not be ready at install time.
    document.body.appendChild(el);
    sentinels.push(el);
  }

  // Repositioning function — re-runs after a tick so layout settles.
  const reposition = (): void => {
    const docHeight = Math.max(
      document.body.scrollHeight,
      document.documentElement.scrollHeight,
    );
    sentinels.forEach((el, i) => {
      const pct = SCROLL_BUCKETS[i];
      // Place at pct% of doc height, clamped so 100% lands within bounds
      el.style.top = Math.max(0, Math.floor((docHeight * pct) / 100) - 2) + "px";
    });
  };
  // Run once + after a small delay for late-rendered content.
  reposition();
  setTimeout(reposition, 1500);

  scrollObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const pct = Number(
        (entry.target as HTMLElement).dataset.viScrollBucket || 0,
      );
      if (!SCROLL_BUCKETS.includes(pct as typeof SCROLL_BUCKETS[number]))
        continue;
      if (scrolledBuckets.has(pct)) continue;
      scrolledBuckets.add(pct);
      enqueue({
        event: "scroll.depth",
        event_id: uuid(),
        session_id: sessionId,
        path: currentPath || window.location.pathname,
        scroll_pct: pct,
      });
    }
  });
  sentinels.forEach((el) => scrollObserver!.observe(el));
}

function clearScrollSentinels(): void {
  document
    .querySelectorAll("[data-vi-scroll-bucket]")
    .forEach((el) => el.remove());
}

function onClickDelegate(ev: MouseEvent): void {
  const target = ev.target as HTMLElement | null;
  if (!target) return;
  // Walk up the DOM looking for data-track
  let el: HTMLElement | null = target;
  let depth = 0;
  while (el && depth < 6) {
    const tag = el.dataset?.track;
    if (tag) {
      // Format expected: "<kind>:<name>" e.g. "cta:enroll_pro"
      // We only emit cta.click for the "cta" kind; other kinds reserved
      // for future event types so the convention stays uniform.
      const [kind, ...rest] = tag.split(":");
      if (kind === "cta") {
        enqueue({
          event: "cta.click",
          event_id: uuid(),
          session_id: getOrCreateSessionId(),
          path: currentPath || window.location.pathname,
          metadata: {
            cta: rest.join(":") || "unnamed",
            text: (el.textContent || "").trim().slice(0, 60),
          },
        });
      }
      return;
    }
    el = el.parentElement;
    depth += 1;
  }
}

// ---- public API ----

export function install(): void {
  // SSR guard: window isn't available during Next.js prerender
  if (typeof window === "undefined") return;
  if (installed) return;
  // Respect Do-Not-Track. Browsers expose it as "1" / "0" / undefined.
  if (
    typeof navigator !== "undefined" &&
    (navigator.doNotTrack === "1" ||
      // @ts-expect-error legacy IE / older Safari
      window.doNotTrack === "1")
  ) {
    return;
  }
  installed = true;

  // Visibility tracking — Page Visibility API
  lastVisibleAtMs = document.visibilityState === "visible" ? Date.now() : 0;
  document.addEventListener("visibilitychange", onVisibilityChange);

  // CTA delegation
  document.addEventListener("click", onClickDelegate, { capture: true });

  // Periodic flush
  flushTimer = setInterval(() => void flush(), FLUSH_INTERVAL_MS);

  // Periodic heartbeat (active time only)
  heartbeatTimer = setInterval(() => {
    if (!currentPath) return;
    if (document.visibilityState !== "visible") return;
    enqueue({
      event: "page.heartbeat",
      event_id: uuid(),
      session_id: getOrCreateSessionId(),
      path: currentPath,
      duration_ms: currentActiveMs(),
    });
  }, HEARTBEAT_INTERVAL_MS);

  // Final flush — best-effort delivery before the tab closes
  const onPageHide = (): void => {
    // Emit exit + session.end + flush synchronously.
    if (currentPath) {
      enqueue({
        event: "page.exit",
        event_id: uuid(),
        session_id: getOrCreateSessionId(),
        path: currentPath,
        duration_ms: currentActiveMs(),
      });
    }
    enqueue({
      event: "session.end",
      event_id: uuid(),
      session_id: getOrCreateSessionId(),
      path: currentPath || window.location.pathname,
    });
    flushSync();
  };
  window.addEventListener("pagehide", onPageHide);
  // beforeunload as a belt for browsers that fire it before pagehide
  window.addEventListener("beforeunload", onPageHide);
}

/**
 * Called from the React mount component on every route change. Emits
 * page.exit for the previous path, then page.view for the new path,
 * and re-installs scroll watchers.
 *
 * Safe to call before install() — it'll no-op until install runs.
 */
export function trackPageView(rawPath: string): void {
  if (typeof window === "undefined") return;
  if (!installed) return;

  const sessionId = getOrCreateSessionId();

  // Capture UTMs from the URL if present
  try {
    captureUtms(new URLSearchParams(window.location.search));
  } catch {
    // ignore parse errors
  }

  // Emit page.exit for the previous page first (if any)
  if (currentPath && currentPath !== rawPath) {
    enqueue({
      event: "page.exit",
      event_id: uuid(),
      session_id: sessionId,
      path: currentPath,
      duration_ms: currentActiveMs(),
    });
  }

  // Reset per-page state
  currentPath = rawPath;
  currentPageStartMs = Date.now();
  activeTimeMs = 0;
  lastVisibleAtMs = document.visibilityState === "visible" ? Date.now() : 0;
  clearScrollSentinels();

  enqueue({
    event: "page.view",
    event_id: uuid(),
    session_id: sessionId,
    path: rawPath,
    referrer: document.referrer || undefined,
  });

  installScrollWatchers(sessionId);
}

/** Programmatic CTA emit — for cases where data-track isn't ergonomic. */
export function trackCta(name: string, metadata?: Record<string, unknown>): void {
  if (typeof window === "undefined" || !installed) return;
  enqueue({
    event: "cta.click",
    event_id: uuid(),
    session_id: getOrCreateSessionId(),
    path: currentPath || window.location.pathname,
    metadata: { cta: name, ...(metadata || {}) },
  });
}

/** Suppress unused warning — referenced by enqueue for type safety only. */
export type { TrackEvent };

// Silence unused-symbol warnings for cosmetic fields used elsewhere
void currentPageStartMs;
