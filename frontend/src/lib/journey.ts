/**
 * Helpers for rendering visitor page journeys in the admin UI.
 */
import type { PageJourneyStep } from "@/types/api";

/** Dwell formatting: seconds-level precision matters here (unlike the
 *  course-watch fmtDuration which rounds to minutes). 95 → "1m 35s". */
export function fmtDwell(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export interface JourneyRow extends PageJourneyStep {
  /** True when this step starts a new browsing session — the UI draws
   *  a session divider above it. */
  newSession: boolean;
}

/** Annotate journey steps with session boundaries, newest session last.
 *  Steps arrive oldest → newest from the API and stay in that order. */
export function buildJourneyRows(steps: PageJourneyStep[]): JourneyRow[] {
  let prevSession: string | null | undefined;
  return steps.map((s) => {
    const newSession = s.session_id !== prevSession;
    prevSession = s.session_id;
    return { ...s, newSession };
  });
}
