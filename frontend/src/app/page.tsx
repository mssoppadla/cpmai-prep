/**
 * Landing page (server-rendered).
 *
 * FAQs and the lead-section copy are fetched from the backend on each
 * request so admins can edit them via /admin/faqs and /admin/settings
 * without redeploying. A fallback copy is used if the API is down.
 */
import { JsonLd, organizationSchema, courseSchema, faqSchema } from "@/components/seo/JsonLd";
import { LeadCaptureForm } from "@/components/lead/LeadCaptureForm";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";

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

export default async function Landing() {
  const [faqs, landing] = await Promise.all([
    fetchJson<typeof FALLBACK_FAQS>("/content/faqs", FALLBACK_FAQS),
    fetchJson<typeof FALLBACK_LANDING>("/content/landing", FALLBACK_LANDING),
  ]);
  const faqPairs = faqs.map(f => ({ q: f.question, a: f.answer }));

  return (
    <>
      <JsonLd data={organizationSchema} />
      <JsonLd data={courseSchema} />
      <JsonLd data={faqSchema(faqPairs)} />

      <SiteHeader active="home" />
      <main className="min-h-screen">
        <header className="max-w-5xl mx-auto px-4 sm:px-6 pt-12 sm:pt-20 md:pt-24
                           pb-10 sm:pb-14 text-center">
          <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold text-slate-900
                         leading-[1.15] tracking-tight">
            Pass the CPMAI certification on your first attempt
          </h1>
          <p className="mt-4 sm:mt-5 text-base sm:text-lg text-slate-600
                        max-w-2xl mx-auto leading-relaxed">
            Realistic mock exams · AI-powered coaching · Detailed answer reasoning
            for every question across all 6 CPMAI phases.
          </p>
        </header>

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
            <dl className="space-y-3 sm:space-y-4">
              {faqs.map(f => (
                <div key={f.id || f.question}
                     className="bg-white p-4 sm:p-5 rounded-xl border border-slate-200">
                  <dt className="font-semibold text-slate-900 text-base">{f.question}</dt>
                  <dd className="mt-2 text-slate-600 text-sm sm:text-base
                                 leading-relaxed">{f.answer}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
