/**
 * /exams — SERVER page for the public mock-exam list.
 *
 * Fetches the active sets + banner copy anonymously server-side so
 * every exam card (title, description, question count, free/premium)
 * ships in the crawlable initial HTML. Signed-in enrichment (attempt
 * counts) happens client-side in ExamsListClient. ISR: 60s.
 */
import type { Metadata } from "next";
import { fetchJson } from "@/lib/ssr";
import type { ExamSetSummaryOut } from "@/types/api";
import { ExamsListClient } from "./ExamsListClient";

export const revalidate = 60;

export const metadata: Metadata = {
  title: "CPMAI Mock Exams & Practice Tests",
  description:
    "Realistic, PMI-standard CPMAI practice exams with per-question "
    + "explanations and domain-level score breakdowns. Free sets open to "
    + "everyone — start a full exam simulation now.",
  alternates: { canonical: "/exams" },
  openGraph: {
    title: "CPMAI Mock Exams & Practice Tests | CPMAI Prep",
    description:
      "Realistic CPMAI practice exams with detailed answer reasoning. "
      + "Free sets open to everyone.",
    url: "/exams",
  },
};

export default async function ExamsPage() {
  const [sets, landing] = await Promise.all([
    fetchJson<ExamSetSummaryOut[] | null>("/exam-sets", null),
    fetchJson<{ exams_anonymous_banner?: string }>("/content/landing", {}),
  ]);
  return (
    <ExamsListClient
      initialSets={Array.isArray(sets) ? sets : null}
      initialAnonBanner={
        typeof landing?.exams_anonymous_banner === "string"
          ? landing.exams_anonymous_banner : null}
    />
  );
}
