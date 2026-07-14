/**
 * robots.txt — crawl rules for search engines.
 *
 * Public marketing/catalog surfaces are open; admin, per-user, and
 * transactional routes are excluded. Exclusion here prevents CRAWLING;
 * the per-segment `robots: { index: false }` metadata (see the small
 * layout.tsx files under dashboard/sessions/exams/[slug]/…) prevents
 * INDEXING — both are needed for pages that might get linked
 * externally.
 */
import type { MetadataRoute } from "next";

const SITE = process.env.NEXT_PUBLIC_SITE_URL || "https://cpmaiexamprep.com";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          "/admin",
          "/dashboard",
          "/sessions",
          "/payments",
          "/exams/results",
          "/login",
          "/api",
        ],
      },
    ],
    sitemap: `${SITE}/sitemap.xml`,
  };
}
