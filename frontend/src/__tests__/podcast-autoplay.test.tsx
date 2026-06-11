/**
 * Course podcast — continuous auto-advance.
 *
 * Pins that when one track ends the player automatically advances to the
 * next lesson (and marks the finished one complete) with no manual click.
 */
import { render, fireEvent, waitFor, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import CoursePodcastPage from "@/app/courses/[slug]/podcast/page";
import { lmsPublic } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    lmsPublic: {
      ...actual.lmsPublic,
      getCourse: vi.fn(),
      myEnrollments: vi.fn(),
      listProgress: vi.fn(),
      updateProgress: vi.fn(),
      savePodcastPointer: vi.fn(),
    },
  };
});

const getCourse = vi.mocked(lmsPublic.getCourse);
const myEnrollments = vi.mocked(lmsPublic.myEnrollments);
const listProgress = vi.mocked(lmsPublic.listProgress);
const updateProgress = vi.mocked(lmsPublic.updateProgress);
const savePodcastPointer = vi.mocked(lmsPublic.savePodcastPointer);

const COURSE_ID = 9;
const detail = {
  course: { id: COURSE_ID, slug: "ml-101", title: "ML 101" },
  is_enrolled: true,
  enrollment_count: 1,
  chapters: [{
    id: 1, title: "Module 1", description: null, position: 10, is_mandatory: false,
    lessons: [
      { id: 1, chapter_id: 1, lesson_type: "video", title: "Intro", position: 10,
        is_mandatory: true, is_free_preview: false, duration_seconds: 10,
        video_url: "/uploads/a.mp4?token=t1", body_blocks: [], files: [] },
      { id: 2, chapter_id: 1, lesson_type: "video", title: "Second", position: 20,
        is_mandatory: true, is_free_preview: false, duration_seconds: 10,
        video_url: "/uploads/b.mp4?token=t2", body_blocks: [], files: [] },
    ],
  }],
} as never;

beforeEach(() => {
  // jsdom doesn't implement media playback — stub so play()/load() don't throw.
  Object.defineProperty(HTMLMediaElement.prototype, "play", {
    configurable: true, value: vi.fn().mockResolvedValue(undefined),
  });
  Object.defineProperty(HTMLMediaElement.prototype, "pause", {
    configurable: true, value: vi.fn(),
  });
  Object.defineProperty(HTMLMediaElement.prototype, "load", {
    configurable: true, value: vi.fn(),
  });
  getCourse.mockReset().mockResolvedValue(detail);
  myEnrollments.mockReset().mockResolvedValue([{ id: 77, course_id: COURSE_ID } as never]);
  listProgress.mockReset().mockResolvedValue([] as never);
  updateProgress.mockReset().mockResolvedValue({} as never);
  savePodcastPointer.mockReset().mockResolvedValue({} as never);
});

afterEach(() => vi.restoreAllMocks());

describe("Course podcast — auto-advance", () => {
  it("advances to the next track and marks the finished one complete on ended", async () => {
    const { container } = render(
      <CoursePodcastPage params={{ slug: "ml-101" }} />,
    );

    // Wait for the player to mount on track 1 (src points at a.mp4).
    await waitFor(() => {
      expect(screen.getByText(/Now playing/i)).toBeInTheDocument();
    });
    const media = container.querySelector("video") as HTMLVideoElement;
    expect(media).toBeTruthy();
    expect(media.getAttribute("src")).toContain("a.mp4");

    // Fire the natural end of track 1 — no manual interaction.
    fireEvent.ended(media);

    // The finished lesson (id 1) is auto-marked complete…
    await waitFor(() => {
      expect(updateProgress).toHaveBeenCalledWith(77, 1, { mark_completed: true });
    });
    // …and the player has auto-advanced to track 2's source.
    await waitFor(() => {
      const v = container.querySelector("video") as HTMLVideoElement;
      expect(v.getAttribute("src")).toContain("b.mp4");
    });
  });
});
