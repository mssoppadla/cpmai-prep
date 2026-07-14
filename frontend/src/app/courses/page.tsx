/**
 * /courses — SERVER page for the public catalog.
 *
 * Fetches the unfiltered catalog + categories server-side so every
 * course card (title, subtitle, price, difficulty) ships in the
 * initial HTML — crawlable by search engines and readable by ad-
 * platform landing-page review. Interactivity (filters, preview
 * lightbox) lives in CoursesCatalogClient, seeded with this data.
 * ISR: refreshed every 60s.
 */
import type { Metadata } from "next";
import { fetchJson } from "@/lib/ssr";
import type { CourseCategoryOut } from "@/types/api";
import {
  CoursesCatalogClient, type CourseWithCategories,
} from "./CoursesCatalogClient";

export const revalidate = 60;

export const metadata: Metadata = {
  title: "CPMAI Courses & Live Training",
  description:
    "Structured, instructor-led CPMAI certification courses — video "
    + "lessons across all 6 phases, live classes, downloadable resources "
    + "and podcasts. Browse the full catalog.",
  alternates: { canonical: "/courses" },
  openGraph: {
    title: "CPMAI Courses & Live Training | CPMAI Prep",
    description:
      "Instructor-led CPMAI certification courses with video lessons, "
      + "live classes and resources.",
    url: "/courses",
  },
};

export default async function CoursesPage() {
  const [courses, categories] = await Promise.all([
    fetchJson<CourseWithCategories[] | null>("/lms/courses", null),
    fetchJson<CourseCategoryOut[]>("/lms/categories", []),
  ]);
  return (
    <CoursesCatalogClient
      initialCourses={Array.isArray(courses) ? courses : null}
      initialCategories={Array.isArray(categories) ? categories : []}
    />
  );
}
