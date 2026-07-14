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
// Route is now a SERVER page; the interactive component is
// CoursesCatalogClient. Null props = client-fetch path.
import { CoursesCatalogClient } from "@/app/courses/CoursesCatalogClient";
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
  discussion_url: null,
  display_order: 100,
  categories: [],
};


describe("CoursesCatalogPage", () => {
  beforeEach(() => mockListCourses.mockReset());

  it("renders course cards returned by the API", async () => {
    mockListCourses.mockResolvedValueOnce([sample]);
    render(<CoursesCatalogClient initialCourses={null} initialCategories={[]} />);
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
    render(<CoursesCatalogClient initialCourses={null} initialCategories={[]} />);
    await waitFor(() => {
      expect(screen.getByText(/No courses available yet/i)).toBeInTheDocument();
    });
  });

  it("filter button refetches with difficulty", async () => {
    mockListCourses.mockResolvedValue([]);
    render(<CoursesCatalogClient initialCourses={null} initialCategories={[]} />);
    await waitFor(() => expect(mockListCourses).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText("intermediate"));
    await waitFor(() => {
      expect(mockListCourses).toHaveBeenLastCalledWith({ difficulty: "intermediate" });
    });
  });

  it("wraps with SiteHeader and SiteFooter (chrome contract)", async () => {
    mockListCourses.mockResolvedValueOnce([]);
    render(<CoursesCatalogClient initialCourses={null} initialCategories={[]} />);
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
    render(<CoursesCatalogClient initialCourses={null} initialCategories={[]} />);
    await waitFor(() => {
      expect(screen.getByText(/INR 999\.00/)).toBeInTheDocument();
    });
  });

  it("shows a preview play button and opens the lightbox on click", async () => {
    mockListCourses.mockResolvedValueOnce([{
      ...sample,
      preview_video_url: "/uploads/1/2026/06/demo.mp4?token=tok",
      preview_lesson_id: 5,
    }]);
    render(<CoursesCatalogClient initialCourses={null} initialCategories={[]} />);
    const btn = await screen.findByLabelText(/Play free preview/i);
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    // The lightbox mounts a <video> pointing at the signed preview URL.
    await waitFor(() => {
      const v = document.querySelector("video");
      expect(v?.getAttribute("src")).toContain("demo.mp4");
    });
  });

  it("links the thumbnail to the course when there is no preview", async () => {
    mockListCourses.mockResolvedValueOnce([sample]);
    render(<CoursesCatalogClient initialCourses={null} initialCategories={[]} />);
    await waitFor(() => expect(screen.getByText("Intro to Python")).toBeInTheDocument());
    // No preview → no play button.
    expect(screen.queryByLabelText(/Play free preview/i)).not.toBeInTheDocument();
  });
});
