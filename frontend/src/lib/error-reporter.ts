/**
 * Client error reporter — feeds /admin/error-logs.
 *
 * Reports the failures the backend can never log itself: requests that
 * died on the wire (QUIC stalls, connection drops, DNS) plus uncaught
 * JS errors. Fire-and-forget by contract — reporting must never add a
 * failure mode of its own, so every path here swallows.
 *
 * Throttling: at most one report per (error_type + path) per 30s, and a
 * hard cap per page lifetime. A flapping connection would otherwise
 * turn one incident into thousands of rows.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

const THROTTLE_MS = 30_000;
const MAX_PER_PAGE = 50;

const lastSent = new Map<string, number>();
let sentCount = 0;

export interface ClientErrorReport {
  source: "network" | "api" | "frontend";
  error_type: string;
  message?: string;
  path?: string;
  method?: string;
  status_code?: number;
  metadata?: Record<string, unknown>;
}

export function reportClientError(err: ClientErrorReport): void {
  try {
    if (typeof window === "undefined") return;
    // Never report failures of the report call itself — loop guard.
    if (err.path?.includes("/errors/report")) return;
    if (sentCount >= MAX_PER_PAGE) return;
    const key = `${err.error_type}:${err.path ?? ""}`;
    const now = Date.now();
    const prev = lastSent.get(key);
    if (prev !== undefined && now - prev < THROTTLE_MS) return;
    lastSent.set(key, now);
    sentCount++;

    const body = JSON.stringify({
      ...err,
      message: (err.message ?? "").slice(0, 2000),
    });
    // keepalive so a report fired during navigation still leaves.
    void fetch(`${BASE}/errors/report`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Anon-Token": window.localStorage.getItem("cpmai.anon_token") ?? "",
      },
      credentials: "same-origin",
      keepalive: true,
      body,
    }).catch(() => { /* reporting is best-effort, never surfaces */ });
  } catch { /* same */ }
}

/** Classify a fetch() rejection into a dashboard-friendly type. Browsers
 *  don't expose net error codes to JS — every wire death is a bare
 *  "Failed to fetch" — so buckets stay coarse on purpose. */
export function classifyNetworkError(e: unknown): string {
  const msg = (e instanceof Error ? e.message : String(e)).toLowerCase();
  if (e instanceof DOMException && e.name === "AbortError") return "TIMEOUT";
  if (msg.includes("failed to fetch") || msg.includes("networkerror")) {
    return "FETCH_FAILED";
  }
  return "NETWORK_OTHER";
}

/** Install window-level handlers for uncaught errors. Idempotent. */
export function installGlobalErrorReporting(): void {
  if (typeof window === "undefined") return;
  const w = window as Window & { __cpmaiErrHooked?: boolean };
  if (w.__cpmaiErrHooked) return;
  w.__cpmaiErrHooked = true;

  window.addEventListener("error", (ev) => {
    reportClientError({
      source: "frontend",
      error_type: "UNCAUGHT_EXCEPTION",
      message: ev.message,
      path: window.location.pathname,
      metadata: { filename: ev.filename, line: ev.lineno, col: ev.colno },
    });
  });
  window.addEventListener("unhandledrejection", (ev) => {
    const r = ev.reason;
    reportClientError({
      source: "frontend",
      error_type: "UNHANDLED_REJECTION",
      message: r instanceof Error ? r.message : String(r),
      path: window.location.pathname,
    });
  });
}
