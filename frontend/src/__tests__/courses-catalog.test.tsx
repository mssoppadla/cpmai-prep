/**
 * /courses (public catalog) smoke tests.
 *
 * Pins:
 *   - Renders the list of courses returned by /lms/courses
 *   - Empty state when no courses
 *   - Difficulty filter triggers a refetch
 *   - SiteHeader + SiteFooter wrap the page (chrome contract)
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import CoursesCatalogPage from "@/app/courses/page";
import { lmsPublic } from "@/lib/api";


vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    lmsPublic: {
      ...actual.lmsPublic,
      listCourses: vi.fn(),
    },
  };
});

const mockListCourses = vi.mocked(lmsPublic.listCourses);

const sample = {
  id: 1, slug: "intro-python", title: "Intro to Python",
  subtitle: "Start your journey", description: null, cover_image_url: null,
  base_price_paise: 0, currency: "INR", enrollment_type: "free" as const,
  difficulty: "beginner" as const, language: "en", estimated_hours: 4,
  learning_outcomes: [], prerequisites_text: null, target_audience: null,
  completion_threshold_percent: 100, lead_instructor_id: null,
  display_order: 100,
};


describe("CoursesCatalogPage", () => {
  beforeEach(() => mockListCourses.mockReset());

  it("renders course cards returned by the API", async () => {
    mockListCourses.mockResolvedValueOnce([sample]);
    render(<CoursesCatalogPage />);
    await waitFor(() => {
      expect(screen.getByText("Intro to Python")).toBeInTheDocument();
    });
    expect(screen.getByText("Start your journey")).toBeInTheDocument();
    expect(screen.getByText("Free")).toBeInTheDocument();
    // "beginner" appears in BOTH the filter pill AND the card badge —
    // assert there are 2 elements, one in the card span and one in the button.
    expect(screen.getAllByText("beginner").length).toBeGreaterThanOrEqual(2);
  });

  it("shows empty state when no courses", async () => {
    mockListCourses.mockResolvedValueOnce([]);
    render(<CoursesCatalogPage />);
    await waitFor(() => {
      expect(screen.getByText(/No courses available yet/i)).toBeInTheDocument();
    });
  });

  it("filter button refetches with difficulty", async () => {
    mockListCourses.mockResolvedValue([]);
    render(<CoursesCatalogPage />);
    await waitFor(() => expect(mockListCourses).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText("intermediate"));
    await waitFor(() => {
      expect(mockListCourses).toHaveBeenLastCalledWith({ difficulty: "intermediate" });
    });
  });

  it("wraps with SiteHeader and SiteFooter (chrome contract)", async () => {
    mockListCourses.mockResolvedValueOnce([]);
    render(<CoursesCatalogPage />);
    await waitFor(() => {
      // Brand from SiteHeader
      expect(screen.getAllByText("CPMAI Prep").length).toBeGreaterThan(0);
    });
    await waitFor(() => {
      // Copyright from SiteFooter
      expect(screen.getByText(/© 2026 CPMAI Prep/i)).toBeInTheDocument();
    });
  });

  it("renders price for paid courses", async () => {
    mockListCourses.mockResolvedValueOnce([{
      ...sample,
      enrollment_type: "paid",
      base_price_paise: 99900,
      currency: "INR",
    }]);
    render(<CoursesCatalogPage />);
    await waitFor(() => {
      expect(screen.getByText(/INR 999\.00/)).toBeInTheDocument();
    });
  });
});
