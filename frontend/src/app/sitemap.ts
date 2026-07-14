/**
 * sitemap.xml — generated on demand, revalidated hourly.
 *
 * Static marketing pages + every published course + every published,
 * PUBLICLY-visible CMS page, pulled from the same public endpoints the
 * pages themselves render from — so a new course or CMS page enters
 * the sitemap automatically, no manual upkeep. Auth-gated routes are
 * deliberately absent (see robots.ts).
 */
import type { MetadataRoute } from "next";
import { API } from "@/lib/ssr";

const SITE = process.env.NEXT_PUBLIC_SITE_URL || "https://cpmaiexamprep.com";

export const revalidate = 3600;

async function safeList<T>(path: string): Promise<T[]> {
  try {
    const r = await fetch(`${API}${path}`, { next: { revalidate: 3600 } });
    if (!r.ok) return [];
    const data = await r.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();

  const statics: MetadataRoute.Sitemap = [
    { url: `${SITE}/`,        lastModified: now, changeFrequency: "daily",  priority: 1.0 },
    { url: `${SITE}/pricing`, lastModified: now, changeFrequency: "daily",  priority: 0.9 },
    { url: `${SITE}/courses`, lastModified: now, changeFrequency: "daily",  priority: 0.9 },
    { url: `${SITE}/exams`,   lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    { url: `${SITE}/privacy`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
    { url: `${SITE}/terms`,   lastModified: now, changeFrequency: "yearly", priority: 0.2 },
  ];

  const [courses, navPages] = await Promise.all([
    safeList<{ slug: string; updated_at?: string }>("/lms/courses"),
    // /cms/nav returns only published pages visible to EVERYONE —
    // exactly the set that belongs in a sitemap.
    safeList<{ slug: string }>("/cms/nav"),
  ]);

  const courseEntries: MetadataRoute.Sitemap = courses
    .filter((c) => typeof c?.slug === "string" && c.slug)
    .map((c) => ({
      url: `${SITE}/courses/${c.slug}`,
      lastModified: c.updated_at ? new Date(c.updated_at) : now,
      changeFrequency: "weekly" as const,
      priority: 0.8,
    }));

  const cmsEntries: MetadataRoute.Sitemap = navPages
    .filter((p) => typeof p?.slug === "string" && p.slug)
    .map((p) => ({
      url: `${SITE}/pages/${p.slug}`,
      lastModified: now,
      changeFrequency: "weekly" as const,
      priority: 0.6,
    }));

  return [...statics, ...courseEntries, ...cmsEntries];
}
