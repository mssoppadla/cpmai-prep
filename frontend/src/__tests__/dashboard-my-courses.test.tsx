/**
 * Dashboard "My courses" section.
 *
 * Pins that enrolled courses render with a server-computed progress bar
 * (progress_percent) + a "Completed" badge, and that the section is
 * hidden when the learner has no enrollments.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import LearnerDashboard from "@/app/(app)/dashboard/page";
import { auth, exams, content, lmsPublic } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    auth: { ...actual.auth, dashboard: vi.fn(), refresh: vi.fn() },
    exams: { ...actual.exams, listSets: vi.fn(), listAttempts: vi.fn() },
    content: { ...actual.content, landing: vi.fn() },
    lmsPublic: { ...actual.lmsPublic, myEnrollments: vi.fn() },
  };
});

const dashboard = vi.mocked(auth.dashboard);
const listSets = vi.mocked(exams.listSets);
const listAttempts = vi.mocked(exams.listAttempts);
const landing = vi.mocked(content.landing);
const myEnrollments = vi.mocked(lmsPublic.myEnrollments);

const DASHBOARD = {
  user: { id: 1, email: "alice@example.com", name: "Alice", role: "user" },
  subscription: { active: false, plan: null, current_period_end: null },
  has_google: false, has_password: true,
} as never;

function enrollment(over: Record<string, unknown>) {
  return {
    id: 1, tenant_id: 1, user_id: 1, course_id: 9, source: "admin_grant",
    enrolled_at: "2026-01-01T00:00:00Z", expires_at: null, revoked_at: null,
    completed_at: null, last_accessed_at: null, granted_by_id: null,
    grant_reason: null, payment_id: null, offer_code_id: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    course_title: "ML 101", course_slug: "ml-101",
    lessons_completed: 3, lessons_total: 10, progress_percent: 30,
    ...over,
  } as never;
}

describe("Dashboard — My courses", () => {
  beforeEach(() => {
    dashboard.mockReset(); listSets.mockReset(); listAttempts.mockReset();
    landing.mockReset(); myEnrollments.mockReset();
    dashboard.mockResolvedValue(DASHBOARD);
    listSets.mockResolvedValue([]);
    listAttempts.mockResolvedValue([]);
    landing.mockResolvedValue(null as never);
  });

  it("renders a progress bar from progress_percent", async () => {
    myEnrollments.mockResolvedValue([enrollment({ progress_percent: 30 })]);
    render(<LearnerDashboard />);
    await waitFor(() => {
      expect(screen.getByText("ML 101")).toBeInTheDocument();
    });
    expect(screen.getByText("3 / 10 lessons")).toBeInTheDocument();
    expect(screen.getByText("30%")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "30");
    expect(bar).toHaveStyle({ width: "30%" });
  });

  it("shows a Completed badge when completed_at is set", async () => {
    myEnrollments.mockResolvedValue([
      enrollment({ completed_at: "2026-02-01T00:00:00Z", progress_percent: 100,
                   lessons_completed: 10 }),
    ]);
    render(<LearnerDashboard />);
    await waitFor(() => {
      expect(screen.getByText("Completed")).toBeInTheDocument();
    });
  });

  it("hides the section when there are no enrollments", async () => {
    myEnrollments.mockResolvedValue([]);
    render(<LearnerDashboard />);
    await waitFor(() => expect(dashboard).toHaveBeenCalled());
    expect(screen.queryByText("Your courses")).not.toBeInTheDocument();
  });
});
