/** Journey rendering helpers — dwell formatting + session dividers. */
import { describe, expect, it } from "vitest";
import { buildJourneyRows, fmtDwell } from "@/lib/journey";
import type { PageJourneyStep } from "@/types/api";

describe("fmtDwell", () => {
  it("formats seconds, minutes, and hours at the right precision", () => {
    expect(fmtDwell(null)).toBe("—");
    expect(fmtDwell(0)).toBe("0s");
    expect(fmtDwell(45)).toBe("45s");
    expect(fmtDwell(60)).toBe("1m");
    expect(fmtDwell(95)).toBe("1m 35s");
    expect(fmtDwell(154.4)).toBe("2m 34s");
    expect(fmtDwell(3660)).toBe("1h 1m");
  });
});

describe("buildJourneyRows", () => {
  const step = (path: string, session_id: string): PageJourneyStep => ({
    path, session_id, entered_at: "2026-07-10T10:00:00Z",
    seconds: null, next_path: null,
  });

  it("marks a divider exactly when the session changes", () => {
    const rows = buildJourneyRows([
      step("/", "s1"), step("/pricing", "s1"),
      step("/exams", "s2"),
      step("/courses", "s2"),
    ]);
    expect(rows.map(r => r.newSession)).toEqual([true, false, true, false]);
  });

  it("handles an empty journey", () => {
    expect(buildJourneyRows([])).toEqual([]);
  });
});
