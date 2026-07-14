/**
 * /courses/[slug] — SERVER page for course detail.
 *
 * Fetches the course anonymously server-side so the hero, description,
 * and full curriculum ship in the initial HTML (crawlable), emits
 * per-course metadata (title/description/cover OG image/canonical) and
 * Course + Offer + BreadcrumbList JSON-LD for Google course rich
 * results. Enrollment-aware interactivity lives in CourseDetailClient,
 * which refetches once on mount to enrich with the viewer's state.
 */
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { JsonLd } from "@/components/seo/JsonLd";
import { fetchJson } from "@/lib/ssr";
import type { CourseDetailPublicOut } from "@/types/api";
import { CourseDetailClient } from "./CourseDetailClient";

export const revalidate = 60;

const SITE = process.env.NEXT_PUBLIC_SITE_URL || "https://cpmaiexamprep.com";

async function loadCourse(slug: string): Promise<CourseDetailPublicOut | null> {
  const d = await fetchJson<CourseDetailPublicOut | null>(
    `/lms/courses/${encodeURIComponent(slug)}`, null);
  // Shape check — 404s and error bodies fall back to null.
  return d && typeof d === "object" && "course" in d ? d : null;
}

export async function generateMetadata(
  { params }: { params: { slug: string } },
): Promise<Metadata> {
  const detail = await loadCourse(params.slug);
  if (!detail) return { title: "Course not found" };
  const c = detail.course;
  const description = (c.subtitle || c.description || "")
    .replace(/\s+/g, " ").slice(0, 160);
  return {
    title: c.title,
    description,
    alternates: { canonical: `/courses/${c.slug}` },
    openGraph: {
      title: `${c.title} | CPMAI Prep`,
      description,
      url: `/courses/${c.slug}`,
      ...(c.cover_image_url ? { images: [{ url: c.cover_image_url }] } : {}),
    },
  };
}

export default async function CourseDetailPage(
  { params }: { params: { slug: string } },
) {
  const detail = await loadCourse(params.slug);
  if (!detail) notFound();
  const c = detail.course;

  const courseLd = {
    "@context": "https://schema.org",
    "@type": "Course",
    name: c.title,
    description: (c.subtitle || c.description || "").slice(0, 500),
    url: `${SITE}/courses/${c.slug}`,
    provider: {
      "@type": "EducationalOrganization",
      name: "CPMAI Prep",
      url: SITE,
    },
    ...(c.cover_image_url ? { image: c.cover_image_url } : {}),
    offers: {
      "@type": "Offer",
      url: `${SITE}/courses/${c.slug}`,
      ...(c.enrollment_type === "free" || !c.base_price_paise
        ? { price: "0", priceCurrency: c.currency || "INR" }
        : { price: (c.base_price_paise / 100).toFixed(2),
            priceCurrency: c.currency }),
      availability: "https://schema.org/InStock",
      category: (c.enrollment_type === "free" || !c.base_price_paise)
        ? "Free" : "Paid",
    },
    hasCourseInstance: {
      "@type": "CourseInstance",
      courseMode: "online",
      ...(c.estimated_hours
        ? { courseWorkload: `PT${c.estimated_hours}H` } : {}),
    },
  };
  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Courses",
        item: `${SITE}/courses` },
      { "@type": "ListItem", position: 2, name: c.title,
        item: `${SITE}/courses/${c.slug}` },
    ],
  };

  return (
    <>
      <JsonLd data={courseLd} />
      <JsonLd data={breadcrumbLd} />
      <CourseDetailClient params={params} initialDetail={detail} />
    </>
  );
}
