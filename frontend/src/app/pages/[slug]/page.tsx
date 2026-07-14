/**
 * Public CMS page renderer at /pages/[slug].
 *
 * This is a server-rendered route (no "use client") so the page is
 * indexable for SEO and ships pre-rendered HTML on first paint. The
 * page-fetch endpoint enforces visibility (anon→401, non-sub→402)
 * so we just translate those into Next's notFound / redirect.
 *
 * We deliberately use the public endpoint here — NOT the admin
 * endpoint — because:
 *   - Drafts must never be visible
 *   - Soft-deleted pages must never be visible
 *   - nav_visibility must gate access (paid pages can't be scraped
 *     by URL by anonymous visitors)
 */
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { cmsPublic } from "@/lib/api";
import { ApiError } from "@/lib/api";
import RenderBlocks from "@/components/cms/RenderBlocks";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";


// Next.js App Router caches `fetch()` calls server-side by default. For
// CMS pages that means the FIRST render of a page is "frozen" — even
// after an admin edits the page in /admin/content-pages, the old
// version keeps serving until the cache TTL expires (or the server
// restarts). That's wrong for a CMS: the operator's edits should appear
// on the next page load. Force every request to re-fetch.
export const dynamic = "force-dynamic";
export const revalidate = 0;


interface Props {
  params: { slug: string };
}


export async function generateMetadata({ params }: Props): Promise<Metadata> {
  try {
    const page = await cmsPublic.page(params.slug);
    return {
      alternates: { canonical: `/pages/${params.slug}` },
      title: page.title,
      description: `${page.title} — CPMAI Prep`,
    };
  } catch {
    return { title: "Not found" };
  }
}


export default async function PublicContentPage({ params }: Props) {
  let page;
  try {
    page = await cmsPublic.page(params.slug);
  } catch (e) {
    // ApiError = backend responded with a non-2xx (404, 401, 402, etc.).
    // Anything else = network failure (backend unreachable, DNS, timeout).
    // For BOTH we render the standard not-found page rather than 500 —
    // the public site must never crash because the backend hiccups.
    // A future PR can render "sign in to unlock" pages for 401/402.
    if (!(e instanceof ApiError)) {
      console.error("[/pages/[slug]] backend unreachable:", e);
    }
    notFound();
  }

  return (
    <>
      <SiteHeader />
      <main className="min-h-screen">
        <article className="max-w-3xl mx-auto px-6 py-10">
          <header className="mb-6">
            <h1 className="text-4xl font-bold text-slate-900 mb-2">{page.title}</h1>
            <p className="text-xs text-slate-500">
              Updated {new Date(page.updated_at).toLocaleDateString()}
            </p>
          </header>
          <div className="prose-cms">
            <RenderBlocks blocks={page.blocks} />
          </div>
        </article>
      </main>
      <SiteFooter />
    </>
  );
}
