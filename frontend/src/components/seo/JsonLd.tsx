/**
 * JsonLd — inject schema.org structured data into the page.
 *
 * The static `<JsonLd data={...} />` component takes a pre-built object
 * and writes it to a `<script type="application/ld+json">` tag.
 *
 * The factory functions (organizationSchema / courseSchema / faqSchema)
 * are CONFIG-DRIVEN: they accept the `SiteChrome` payload (or a subset)
 * and emit a schema object that reflects what the admin has configured
 * in /admin/settings. So updating LinkedIn / YouTube / brand_name in
 * the settings UI immediately changes the SEO structured data without
 * a code change.
 *
 * Each factory accepts an optional `siteUrl` (falls back to
 * NEXT_PUBLIC_SITE_URL) and `chrome` (falls back to empty values that
 * render harmless absent fields).
 */
import type { SiteChrome } from "@/types/api";


const DEFAULT_SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://cpmaiexamprep.com";


export function JsonLd({ data }: { data: object }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}


/** Organisation schema. `sameAs` is built from whatever social URLs
 *  the admin has set in /admin/settings (empty values omitted). */
export function organizationSchema(opts: {
  chrome?: Partial<SiteChrome>;
  siteUrl?: string;
} = {}): object {
  const url = opts.siteUrl ?? DEFAULT_SITE_URL;
  const chrome = opts.chrome ?? {};
  const sameAs = [
    chrome.linkedin_url,
    chrome.twitter_url,
    chrome.youtube_url,
    chrome.instagram_url,
    chrome.facebook_url,
    chrome.threads_url,
    chrome.tiktok_url,
    chrome.github_url,
  ].filter((u): u is string => typeof u === "string" && u.length > 0);

  const out: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "EducationalOrganization",
    name: chrome.brand_name || "CPMAI Prep",
    url,
    logo: `${url.replace(/\/$/, "")}/logo.png`,
  };
  if (sameAs.length > 0) out.sameAs = sameAs;
  return out;
}


/** Course schema — title + description configurable via the brand_name
 *  + tagline chrome fields (admin can rebrand the org without touching
 *  code). Keeps the existing certificate-prep focus. */
export function courseSchema(opts: {
  chrome?: Partial<SiteChrome>;
  siteUrl?: string;
} = {}): object {
  const url = opts.siteUrl ?? DEFAULT_SITE_URL;
  const chrome = opts.chrome ?? {};
  return {
    "@context": "https://schema.org",
    "@type": "Course",
    name: `${chrome.brand_name || "CPMAI Prep"} — Certification Preparation`,
    description: chrome.tagline ||
      "Comprehensive preparation for the Cognitive Project Management for AI certification.",
    provider: {
      "@type": "Organization",
      name: chrome.brand_name || "CPMAI Prep",
      sameAs: url,
    },
    hasCourseInstance: {
      "@type": "CourseInstance",
      courseMode: "online",
      courseWorkload: "PT60H",
    },
  };
}


export const faqSchema = (qs: { q: string; a: string }[]) => ({
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: qs.map(({ q, a }) => ({
    "@type": "Question",
    name: q,
    acceptedAnswer: { "@type": "Answer", text: a },
  })),
});
