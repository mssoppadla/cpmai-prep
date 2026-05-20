/**
 * /admin/courses (admin list) smoke tests.
 *
 * Pins:
 *   - Renders courses from the API
 *   - + New course form validation (slug regex + title required)
 *   - Empty state
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import CoursesAdminPage from "@/app/admin/courses/page";
import { admin } from "@/lib/api";


vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    admin: {
      ...actual.admin,
      lms: {
        ...actual.admin.lms,
        listCourses: vi.fn(),
        createCourse: vi.fn(),
        deleteCourse: vi.fn(),
      },
    },
  };
});
const m = vi.mocked(admin.lms);

const sample = {
  id: 1, tenant_id: 1, slug: "intro-python", title: "Intro to Python",
  subtitle: null, description: null, cover_image_url: null,
  base_price_paise: 0, currency: "INR", plan_id: null,
  enrollment_type: "free" as const, difficulty: "beginner" as const,
  language: "en", estimated_hours: null, learning_outcomes: [],
  prerequisites_text: null, target_audience: null,
  completion_threshold_percent: 100, lead_instructor_id: null,
  discussion_url: null,
  display_order: 100, is_published: true, is_deleted: false,
  deleted_at: null, deleted_by: null, created_by: 1,
  created_at: "", updated_at: "",
};


describe("CoursesAdminPage", () => {
  beforeEach(() => {
    m.listCourses.mockReset();
    m.createCourse.mockReset();
    m.deleteCourse.mockReset();
  });

  it("renders rows from API", async () => {
    m.listCourses.mockResolvedValueOnce([sample]);
    render(<CoursesAdminPage />);
    await waitFor(() => {
      expect(screen.getByText("Intro to Python")).toBeInTheDocument();
    });
    expect(screen.getByText("beginner")).toBeInTheDocument();
    expect(screen.getByText(/Published/i)).toBeInTheDocument();
  });

  it("empty state when no courses", async () => {
    m.listCourses.mockResolvedValueOnce([]);
    render(<CoursesAdminPage />);
    await waitFor(() => {
      expect(screen.getByText(/No courses yet/i)).toBeInTheDocument();
    });
  });

  it("validates slug on create", async () => {
    m.listCourses.mockResolvedValueOnce([]);
    render(<CoursesAdminPage />);
    await waitFor(() => screen.getByText(/No courses yet/i));
    fireEvent.click(screen.getByRole("button", { name: /\+ New course/ }));
    fireEvent.change(screen.getByPlaceholderText("intro-to-python"),
                     { target: { value: "Bad Slug" } });
    fireEvent.change(screen.getByPlaceholderText("Intro to Python"),
                     { target: { value: "Title" } });
    fireEvent.click(screen.getByRole("button", { name: /Create and open editor/ }));
    await waitFor(() => {
      expect(screen.getByText(/Slug must be lowercase/i)).toBeInTheDocument();
    });
    expect(m.createCourse).not.toHaveBeenCalled();
  });

  it("validates title required on create", async () => {
    m.listCourses.mockResolvedValueOnce([]);
    render(<CoursesAdminPage />);
    await waitFor(() => screen.getByText(/No courses yet/i));
    fireEvent.click(screen.getByRole("button", { name: /\+ New course/ }));
    fireEvent.change(screen.getByPlaceholderText("intro-to-python"),
                     { target: { value: "valid-slug" } });
    fireEvent.click(screen.getByRole("button", { name: /Create and open editor/ }));
    await waitFor(() => {
      expect(screen.getByText(/Title is required/i)).toBeInTheDocument();
    });
    expect(m.createCourse).not.toHaveBeenCalled();
  });

  it("delete confirmation prevents accidental delete", async () => {
    m.listCourses.mockResolvedValueOnce([sample]);
    render(<CoursesAdminPage />);
    await waitFor(() => screen.getByText("Intro to Python"));
    vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    fireEvent.click(screen.getByText("Delete"));
    expect(m.deleteCourse).not.toHaveBeenCalled();
  });
});
