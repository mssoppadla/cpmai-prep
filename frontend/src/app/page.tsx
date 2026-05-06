import { JsonLd, organizationSchema, courseSchema, faqSchema } from "@/components/seo/JsonLd";
import { LeadCaptureForm } from "@/components/lead/LeadCaptureForm";
import { LandingTopBar } from "@/components/layout/LandingTopBar";

const FAQS = [
  { q: "What is the CPMAI certification?",
    a: "CPMAI (Cognitive Project Management for AI) is a vendor-neutral certification covering a 6-phase methodology for managing AI and data science projects." },
  { q: "How long does it take to prepare?",
    a: "Most candidates need 6-8 weeks of focused study covering all 6 phases plus mock exams." },
  { q: "Does CPMAI Prep guarantee passing?",
    a: "We don't guarantee outcomes, but our learners consistently outperform the average pass rate by combining mock exams with AI-powered coaching." },
];

export default function Landing() {
  return (
    <>
      <JsonLd data={organizationSchema} />
      <JsonLd data={courseSchema} />
      <JsonLd data={faqSchema(FAQS)} />

      <main className="min-h-screen">
        <LandingTopBar />
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
            Start with our free CPMAI study guide
          </h2>
          <LeadCaptureForm
            source="landing_hero"
            fields={["name", "target_exam_date"]}
            cta="Get the free guide"
          />
        </section>

        <section aria-labelledby="faq-heading"
                 className="max-w-3xl mx-auto px-4 sm:px-6 pb-20 sm:pb-24">
          <h2 id="faq-heading"
              className="text-xl sm:text-2xl font-bold text-slate-900 mb-5 sm:mb-6">
            Frequently asked questions
          </h2>
          <dl className="space-y-3 sm:space-y-4">
            {FAQS.map(f => (
              <div key={f.q}
                   className="bg-white p-4 sm:p-5 rounded-xl border border-slate-200">
                <dt className="font-semibold text-slate-900 text-base">{f.q}</dt>
                <dd className="mt-2 text-slate-600 text-sm sm:text-base
                               leading-relaxed">{f.a}</dd>
              </div>
            ))}
          </dl>
        </section>
      </main>
    </>
  );
}
