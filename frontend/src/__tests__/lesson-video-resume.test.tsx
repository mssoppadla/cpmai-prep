/**
 * Lesson player video — resume + auto-complete.
 *
 * Pins the two behaviours that were previously missing:
 *   - On metadata load, the <video> seeks to the server-saved
 *     last_position_seconds (resume across refresh / devices).
 *   - On the video 'ended' event, the lesson is auto-marked complete.
 */
import { render, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import LessonPlayerPage from "@/app/courses/[slug]/lessons/[lid]/page";
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
      getMyNote: vi.fn(),
    },
  };
});

const getCourse = vi.mocked(lmsPublic.getCourse);
const myEnrollments = vi.mocked(lmsPublic.myEnrollments);
const listProgress = vi.mocked(lmsPublic.listProgress);
const updateProgress = vi.mocked(lmsPublic.updateProgress);
const getMyNote = vi.mocked(lmsPublic.getMyNote);

const LESSON_ID = 5;
const COURSE_ID = 9;

const detail = {
  course: { id: COURSE_ID, slug: "ml-101", title: "ML 101", discussion_url: null },
  is_enrolled: true,
  enrollment_count: 1,
  chapters: [{
    id: 1, title: "Module 1", description: null, position: 10, is_mandatory: false,
    lessons: [{
      id: LESSON_ID, chapter_id: 1, lesson_type: "video", title: "Intro",
      position: 10, is_mandatory: true, is_free_preview: false,
      duration_seconds: 100, discussion_url: null,
      video_url: "/uploads/1/2026/06/abc-intro.mp4?token=tok",
      body_blocks: [], files: [],
    }],
  }],
} as never;

const progressRow = {
  lesson_id: LESSON_ID, last_position_seconds: 42, watch_time_seconds: 42,
  completed_at: null, first_completed_at: null, checklist_state: {},
};

beforeEach(() => {
  getCourse.mockReset(); myEnrollments.mockReset();
  listProgress.mockReset(); updateProgress.mockReset(); getMyNote.mockReset();
  getCourse.mockResolvedValue(detail);
  myEnrollments.mockResolvedValue([{ id: 77, course_id: COURSE_ID } as never]);
  listProgress.mockResolvedValue([progressRow] as never);
  updateProgress.mockResolvedValue(progressRow as never);
  getMyNote.mockResolvedValue(null as never);
});

async function renderPlayer() {
  const utils = render(
    <LessonPlayerPage params={{ slug: "ml-101", lid: String(LESSON_ID) }} />,
  );
  // Wait for the video element to appear (course + progress loaded).
  let video: HTMLVideoElement | null = null;
  await waitFor(() => {
    video = utils.container.querySelector("video");
    expect(video).not.toBeNull();
  });
  return { ...utils, video: video as unknown as HTMLVideoElement };
}

describe("Lesson player video resume + auto-complete", () => {
  it("seeks to the saved position on loadedmetadata", async () => {
    const { video } = await renderPlayer();
    // jsdom doesn't compute duration — define it so the seek guard passes.
    Object.defineProperty(video, "duration", { value: 100, configurable: true });
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(42);
  });

  it("does not seek past the end of a fully-watched video", async () => {
    listProgress.mockResolvedValue([{ ...progressRow, last_position_seconds: 99 }] as never);
    const { video } = await renderPlayer();
    Object.defineProperty(video, "duration", { value: 100, configurable: true });
    fireEvent.loadedMetadata(video);
    // 99 is within 2s of the 100s end → start from 0, not 99.
    expect(video.currentTime).toBe(0);
  });

  it("auto-marks complete when the video ends", async () => {
    const { video } = await renderPlayer();
    updateProgress.mockClear();
    fireEvent.ended(video);
    await waitFor(() => {
      expect(updateProgress).toHaveBeenCalledWith(77, LESSON_ID, { mark_completed: true });
    });
  });
});
