import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { JsonLd } from "@/components/seo/JsonLd";
import { fetchJson } from "@/lib/ssr";
import { labPagePath } from "@/lib/labs";
import type { LabIndexOut } from "@/types/api";
import { LabEmbedClient } from "../LabEmbedClient";

/**
 * Generic page for every registry-driven lab (backend
 * app/core/labs_registry.py). Adding a lab = one registry entry + its
 * asset under frontend/labs-assets/ — this route picks it up, with
 * SEO metadata, structured data and a crawlable section outline.
 * Labs with their own bespoke folder (metrics-lab, the Simulator) keep
 * it: Next prefers the static route over this dynamic one.
 */

const SITE = "CPMAI Exam Prep";

async function loadLab(slug: string): Promise<LabIndexOut | null> {
  const labs = await fetchJson<LabIndexOut[]>("/content/labs", []);
  return labs.find(l => l.slug === slug) ?? null;
}

export async function generateMetadata(
  { params }: { params: { slug: string } },
): Promise<Metadata> {
  const lab = await loadLab(params.slug);
  if (!lab) return { title: "Lab", robots: { index: false } };
  const path = labPagePath(lab.slug);
  return {
    // The root layout appends the site name — don't repeat it here.
    title: `${lab.title} — ${lab.domain.replace(/^D-[IV]+ · /, "")}`,
    description: lab.blurb,
    alternates: { canonical: path },
    openGraph: {
      title: `${lab.title} — CPMAI visual walkthrough`,
      description: lab.blurb,
      type: "website",
      url: path,
    },
    robots: lab.enabled ? { index: true, follow: true } : { index: false },
  };
}

export default async function LabPage({ params }: { params: { slug: string } }) {
  const lab = await loadLab(params.slug);
  if (!lab) notFound();
  if (!lab.enabled) redirect("/labs");
  const path = labPagePath(lab.slug);
  return (
    <>
      <JsonLd data={{
        "@context": "https://schema.org",
        "@type": "LearningResource",
        name: lab.title,
        description: lab.blurb,
        url: path,
        educationalLevel: "Professional certification preparation",
        learningResourceType: lab.group === "walkthrough"
          ? "Visual walkthrough" : "Interactive simulation",
        timeRequired: `PT${lab.minutes}M`,
        teaches: lab.teaches,
        hasPart: lab.sections.map((s, i) => ({
          "@type": "Chapter", position: i + 1, name: s.title,
        })),
        isAccessibleForFree: lab.mode === "free",
        provider: { "@type": "Organization", name: SITE },
      }} />
      <SiteHeader active="labs" />
      <main className="max-w-[1400px] mx-auto px-4 sm:px-6 py-8 sm:py-10">
        <p className="text-xs text-slate-500 mb-2">Labs → {lab.title}</p>
        <h1 className="text-3xl font-bold text-slate-900 mb-2">{lab.title}</h1>
        <p className="text-slate-600 mb-4 max-w-3xl">{lab.blurb}</p>
        <div className="flex flex-wrap gap-2 mb-4">
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700">
            {lab.domain}
          </span>
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-800">
            ~{lab.minutes} min
          </span>
        </div>
        {lab.sections.length > 0 && (
          /* Crawlable outline of the page — the content itself is an
             embedded document. Visually hidden, read by search engines
             and screen readers. */
          <nav aria-label="Sections on this page" className="sr-only">
            <h2>What this page covers</h2>
            <ol>{lab.sections.map(s => <li key={s.id}>{s.title}</li>)}</ol>
          </nav>
        )}
        <LabEmbedClient slug={lab.slug} title={lab.title} pagePath={path} />
      </main>
      <SiteFooter />
    </>
  );
}
