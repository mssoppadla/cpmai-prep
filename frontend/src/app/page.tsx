/**
 * Landing page (server-rendered).
 *
 * Two paths through this route:
 *
 *  1. **CMS landing override**. If the operator has marked a content_page
 *     as the landing page AND enabled the ``cms.use_cms_landing`` setting,
 *     the backend's /cms/landing endpoint returns that page and we render
 *     its BlockNote blocks via ``RenderBlocks``. Marketing copy is bypassed.
 *
 *  2. **Marketing default**. Otherwise we render the legacy marketing
 *     landing — hero + lead form + FAQs. FAQs and lead copy are fetched
 *     from the backend on each request so admins can edit them via
 *     /admin/faqs and /admin/settings without redeploying. A fallback
 *     copy is used if the API is down.
 *
 * The CMS-landing branch is gated by the setting so the operator can
 * preview a CMS landing in admin without it going live. Flipping the
 * setting in /admin/settings is the "publish landing" action.
 */
import Link from "next/link";
import { GraduationCap, ClipboardCheck, ArrowRight } from "lucide-react";
import type { ContentPagePublicOut, SiteChrome } from "@/types/api";
import { JsonLd, organizationSchema, courseSchema, faqSchema } from "@/components/seo/JsonLd";
import { LeadCaptureForm } from "@/components/lead/LeadCaptureForm";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import RenderBlocks from "@/components/cms/RenderBlocks";


// CMS-aware landing route: must re-fetch on every request so that
// toggling the cms.use_cms_landing setting OR editing the landing
// page takes effect on the very next load. Without this, Next's
// default fetch cache would freeze the FIRST render's outcome.
export const dynamic = "force-dynamic";
export const revalidate = 0;

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

const FALLBACK_FAQS = [
  { id: 0, question: "What is the CPMAI certification?",
    answer: "CPMAI (Cognitive Project Management for AI) is a vendor-neutral certification covering a 6-phase methodology for managing AI and data science projects.",
    display_order: 10 },
];

const FALLBACK_LANDING = {
  lead_section_heading: "Start with our free CPMAI study guide",
  lead_cta_text: "Get the free guide",
  lead_post_submit_route: "/exams",
  // Hero copy fallbacks — used when /content/landing is unreachable
  // at build/render time. Kept in sync with the seeded defaults so
  // the page never shows a blank H1.
  hero_headline: "Pass the CPMAI certification on your first attempt",
  hero_subtitle:
    "Realistic mock exams · AI-powered coaching · Detailed answer " +
    "reasoning for every question across all 6 CPMAI phases.",
};

async function fetchJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(`${API}${path}`, { cache: "no-store" });
    if (!r.ok) return fallback;
    return await r.json();
  } catch {
    return fallback;
  }
}

/**
 * Try to fetch the CMS landing page. Returns null on 404 (no landing
 * configured OR setting disabled) and on any other error — the
 * marketing page is the safe fallback.
 */
async function fetchCmsLanding(): Promise<ContentPagePublicOut | null> {
  try {
    const r = await fetch(`${API}/cms/landing`, { cache: "no-store" });
    if (!r.ok) return null;
    const data = await r.json();
    // Defensive validation — only proceed if the response actually
    // looks like a page payload. Anything else (e.g. test mocks
    // returning `[]` or `{}` for unmatched routes) falls back to the
    // marketing homepage so we don't crash on missing fields.
    if (data && typeof data === "object" && !Array.isArray(data)
        && typeof (data as { slug?: unknown }).slug === "string"
        && Array.isArray((data as { blocks?: unknown }).blocks)) {
      return data as ContentPagePublicOut;
    }
    return null;
  } catch {
    return null;
  }
}


export default async function Landing() {
  // 1. Check the CMS landing path first. When the operator has set a
  //    page AND enabled the setting, render that and skip the marketing
  //    flow entirely.
  const cmsLanding = await fetchCmsLanding();
  if (cmsLanding) {
    return (
      <>
        <SiteHeader active="home" />
        <main className="min-h-screen">
          <article className="max-w-3xl mx-auto px-6 py-10">
            <header className="mb-6">
              <h1 className="text-4xl font-bold text-slate-900 mb-2">
                {cmsLanding.title}
              </h1>
            </header>
            <div className="prose-cms">
              <RenderBlocks blocks={cmsLanding.blocks} />
            </div>
          </article>
        </main>
        <SiteFooter />
      </>
    );
  }

  // 2. Default — render the existing marketing landing.
  // Pull site chrome in parallel so JSON-LD's organization/sameAs etc.
  // reflect whatever the admin has configured in /admin/settings.
  const [faqs, landing, chrome] = await Promise.all([
    fetchJson<typeof FALLBACK_FAQS>("/content/faqs", FALLBACK_FAQS),
    fetchJson<typeof FALLBACK_LANDING>("/content/landing", FALLBACK_LANDING),
    fetchJson<Partial<SiteChrome>>("/content/site", {}),
  ]);
  const faqPairs = faqs.map(f => ({ q: f.question, a: f.answer }));

  return (
    <>
      <JsonLd data={organizationSchema({ chrome })} />
      <JsonLd data={courseSchema({ chrome })} />
      <JsonLd data={faqSchema(faqPairs)} />

      <SiteHeader active="home" />
      <main className="min-h-screen">
        <header className="max-w-5xl mx-auto px-4 sm:px-6 pt-12 sm:pt-20 md:pt-24
                           pb-10 sm:pb-14 text-center">
          <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold text-slate-900
                         leading-[1.15] tracking-tight">
            {landing.hero_headline}
          </h1>
          <p className="mt-4 sm:mt-5 text-base sm:text-lg text-slate-600
                        max-w-2xl mx-auto leading-relaxed">
            {landing.hero_subtitle}
          </p>
        </header>

        {/* Two ways to prepare — surfaces both product lines (courses +
            mock exams) to first-time visitors right under the hero, so
            discovery doesn't depend on finding the nav links. */}
        <section aria-labelledby="paths-heading"
                 className="max-w-5xl mx-auto px-4 sm:px-6 pb-14 sm:pb-16">
          <h2 id="paths-heading"
              className="text-xl sm:text-2xl font-bold text-slate-900 text-center">
            Two ways to prepare
          </h2>
          <p className="mt-2 text-center text-slate-600 text-sm sm:text-base max-w-2xl mx-auto">
            Build deep understanding with structured courses, then prove you&apos;re
            exam-ready with realistic mock exams.
          </p>
          <div className="mt-8 grid sm:grid-cols-2 gap-4 sm:gap-5">
            <Link href="/courses"
                  className="group block bg-white border border-slate-200 rounded-2xl p-6 hover:border-indigo-300 hover:shadow-md transition">
              <div className="w-11 h-11 rounded-xl bg-indigo-50 text-indigo-600 grid place-items-center">
                <GraduationCap size={22} />
              </div>
              <h3 className="mt-4 text-lg font-semibold text-slate-900">Structured courses</h3>
              <p className="mt-1.5 text-sm text-slate-600 leading-relaxed">
                Step-by-step lessons across all 6 CPMAI phases — video, downloadable
                resources, and a listen-anywhere podcast.
              </p>
              <span className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-indigo-600 group-hover:gap-2.5 transition-all">
                Browse courses <ArrowRight size={16} />
              </span>
            </Link>
            <Link href="/exams"
                  className="group block bg-white border border-slate-200 rounded-2xl p-6 hover:border-emerald-300 hover:shadow-md transition">
              <div className="w-11 h-11 rounded-xl bg-emerald-50 text-emerald-600 grid place-items-center">
                <ClipboardCheck size={22} />
              </div>
              <h3 className="mt-4 text-lg font-semibold text-slate-900">Mock exams</h3>
              <p className="mt-1.5 text-sm text-slate-600 leading-relaxed">
                Realistic, PMI-standard practice exams with per-question explanations
                and domain-level score breakdowns.
              </p>
              <span className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-emerald-700 group-hover:gap-2.5 transition-all">
                Try a mock exam <ArrowRight size={16} />
              </span>
            </Link>
          </div>
        </section>

        <section aria-labelledby="lead-heading"
                 className="max-w-md mx-auto px-4 sm:px-6 pb-16 sm:pb-20">
          <h2 id="lead-heading"
              className="text-lg sm:text-xl font-semibold text-slate-900 text-center mb-4">
            {landing.lead_section_heading}
          </h2>
          <LeadCaptureForm
            source="landing_hero"
            fields={["name", "whatsapp", "target_exam_date"]}
            cta={landing.lead_cta_text}
            postSubmitRoute={landing.lead_post_submit_route}
          />
        </section>

        <section aria-labelledby="faq-heading"
                 className="max-w-3xl mx-auto px-4 sm:px-6 pb-20 sm:pb-24">
          <h2 id="faq-heading"
              className="text-xl sm:text-2xl font-bold text-slate-900 mb-5 sm:mb-6">
            Frequently asked questions
          </h2>
          {faqs.length === 0 ? (
            <p className="text-slate-500 text-sm">No FAQs published yet.</p>
          ) : (
            // Native <details>/<summary> accordion — no client JS, fully
            // keyboard-accessible, works without hydration. First item
            // opens by default so the section doesn't look empty.
            <div className="space-y-3 sm:space-y-4">
              {faqs.map((f, i) => (
                <details key={f.id || f.question}
                         open={i === 0}
                         className="group bg-white rounded-xl border border-slate-200
                                    open:shadow-sm transition-shadow">
                  <summary className="cursor-pointer list-none flex items-center justify-between
                                      gap-3 p-4 sm:p-5 font-semibold text-slate-900 text-base
                                      [&::-webkit-details-marker]:hidden">
                    <span>{f.question}</span>
                    <svg
                      className="flex-shrink-0 w-5 h-5 text-slate-400 transition-transform
                                 group-open:rotate-180"
                      viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                      <path fillRule="evenodd"
                            d="M5.23 7.21a.75.75 0 011.06.02L10 11.06l3.71-3.83a.75.75 0 111.08 1.04l-4.25 4.4a.75.75 0 01-1.08 0l-4.25-4.4a.75.75 0 01.02-1.06z"
                            clipRule="evenodd" />
                    </svg>
                  </summary>
                  <div className="px-4 sm:px-5 pb-4 sm:pb-5 text-slate-600 text-sm sm:text-base
                                  leading-relaxed">{f.answer}</div>
                </details>
              ))}
            </div>
          )}
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
