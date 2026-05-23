/**
 * /terms — Terms of Service page.
 *
 * Static page wrapped in SiteHeader + SiteFooter so the footer's
 * /terms link doesn't 404. The copy is a reasonable starting point;
 * admin can swap it for legal-team-reviewed text later (or migrate to
 * a CMS-managed page at /pages/terms once the legal text stabilises).
 *
 * Why a server component (no "use client"):
 *   • Pure static content; no state, no event handlers
 *   • Better SEO — fully rendered in the initial HTML
 *   • Smaller bundle
 *
 * To update the copy: edit this file. To migrate to CMS:
 *   1. Create a content page in /admin/content-pages with slug "terms"
 *   2. Add a next.config rewrite: `{ source: "/terms", destination: "/pages/terms" }`
 *   3. Delete this file
 */
import type { Metadata } from "next";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import type { SiteChrome } from "@/types/api";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "Terms and conditions governing the use of CPMAI Prep.",
  alternates: { canonical: "/terms" },
};

const LAST_UPDATED = "2026-05-21";

/** Server-side fetch of the chrome so contact emails reflect what the
 *  admin configured in /admin/settings. Falls back to the hardcoded
 *  defaults so this page can never crash on a chrome-endpoint outage. */
async function getChrome(): Promise<Partial<SiteChrome>> {
  try {
    const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
    const r = await fetch(`${base}/content/site`, { next: { revalidate: 300 } });
    if (!r.ok) return {};
    return await r.json();
  } catch {
    return {};
  }
}


export default async function TermsPage() {
  const chrome = await getChrome();
  const supportEmail = chrome.support_email || "support@cpmaiexamprep.com";
  return (
    <>
      <SiteHeader />
      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-12 prose prose-slate">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Terms of Service</h1>
        <p className="text-sm text-slate-500 mb-8">Last updated: {LAST_UPDATED}</p>

        <Section title="1. Agreement to Terms">
          <p>
            By accessing or using CPMAI Prep (the &ldquo;Service&rdquo;) you agree to be
            bound by these Terms of Service. If you do not agree to these
            terms, do not access or use the Service.
          </p>
        </Section>

        <Section title="2. Description of Service">
          <p>
            CPMAI Prep provides online learning content, practice exams,
            an AI assistant, and related study tools for the CPMAI
            certification. The Service is operated by the entity listed
            in the Contact section at the foot of this page.
          </p>
        </Section>

        <Section title="3. Eligibility and Account Registration">
          <p>
            You must be at least 18 years old, or have the consent of a
            parent or legal guardian, to create an account. You agree to
            provide accurate, current and complete information during
            registration and to keep your account credentials secure.
          </p>
          <p>
            You are responsible for all activity that occurs under your
            account. Notify us immediately of any unauthorised access.
          </p>
        </Section>

        <Section title="4. Subscriptions and Payments">
          <p>
            Paid plans are billed through Razorpay (or an equivalent
            processor we make available). Prices, billing intervals and
            features for each plan are listed on the{" "}
            <a href="/pricing" className="text-indigo-600 hover:underline">
              pricing page
            </a>{" "}
            and may be revised from time to time. Existing subscriptions
            are honoured at their original price until renewal.
          </p>
          <p>
            All payments are non-refundable except where required by
            applicable law (e.g. the Consumer Protection Act, 2019 in
            India) or where this is stated explicitly elsewhere on the
            Service. Subscriptions cancel automatically at the end of
            the current billing period if not renewed.
          </p>
          <p>
            GST and other applicable taxes are charged at the prevailing
            statutory rate for customers in India and are itemised on
            every invoice.
          </p>
        </Section>

        <Section title="5. Acceptable Use">
          <p>You agree NOT to:</p>
          <ul>
            <li>Reproduce, redistribute or publicly display Service content without permission</li>
            <li>Share your account credentials or attempt to defeat access controls (e.g. by recording live sessions to share with non-subscribers)</li>
            <li>Use automated tools to scrape, harvest or extract data from the Service</li>
            <li>Upload or post unlawful, infringing, harassing, or malicious content</li>
            <li>Interfere with the integrity, performance or security of the Service</li>
            <li>Reverse-engineer or attempt to derive source code from any part of the Service</li>
          </ul>
          <p>
            Violation of this section may result in suspension or
            termination of your account without refund.
          </p>
        </Section>

        <Section title="6. Intellectual Property">
          <p>
            All course content, question banks, software, branding and
            other materials forming part of the Service are the property
            of CPMAI Prep or its licensors and are protected by Indian
            and international copyright, trademark and other intellectual
            property laws. Your subscription grants a limited, personal,
            non-transferable, non-sublicensable licence to access the
            Service for self-study; no other rights are granted.
          </p>
        </Section>

        <Section title="7. AI Assistant and Generated Content">
          <p>
            The AI assistant produces answers grounded in our content
            but may occasionally be incomplete or incorrect. Do not rely
            on AI output as a substitute for verified study materials,
            professional advice, or official certification authority
            guidance. Conversations may be reviewed by administrators
            for quality, abuse and audit purposes (see our{" "}
            <a href="/privacy" className="text-indigo-600 hover:underline">
              Privacy Policy
            </a>
            ).
          </p>
        </Section>

        <Section title="8. Live Sessions and Recordings">
          <p>
            Live Zoom sessions are accessible only from within the
            Service for logged-in subscribers. Recording, screen-capturing
            or otherwise duplicating live sessions or recorded content
            for redistribution is strictly prohibited and grounds for
            immediate termination.
          </p>
        </Section>

        <Section title="9. Refund and Cancellation Policy">
          <p>
            You may cancel your subscription at any time from your
            account settings; cancellation takes effect at the end of
            the current billing period. Refunds for partial-period usage
            are not issued except in cases of demonstrable error on our
            part or where required by law.
          </p>
        </Section>

        <Section title="10. Data and Privacy">
          <p>
            Our handling of personal data is governed by our{" "}
            <a href="/privacy" className="text-indigo-600 hover:underline">
              Privacy Policy
            </a>
            . By using the Service you consent to that policy.
          </p>
        </Section>

        <Section title="11. Termination">
          <p>
            We may suspend or terminate your access at any time, with or
            without notice, if you breach these Terms or if continued
            access poses a risk to the Service or other users. You may
            terminate your account at any time using the &ldquo;Delete my
            account&rdquo; option in your account settings.
          </p>
        </Section>

        <Section title="12. Disclaimer and Limitation of Liability">
          <p>
            The Service is provided &ldquo;as is&rdquo; without warranties
            of any kind, express or implied. To the maximum extent
            permitted by applicable law, our aggregate liability arising
            out of or related to your use of the Service shall not exceed
            the amount you paid us in the twelve months preceding the
            claim. We are not liable for indirect, incidental or
            consequential damages.
          </p>
        </Section>

        <Section title="13. Governing Law and Jurisdiction">
          <p>
            These Terms are governed by the laws of India. Any disputes
            arising from these Terms or your use of the Service will be
            resolved exclusively in the courts of Hyderabad, Telangana,
            unless a different forum is required by mandatory law.
          </p>
        </Section>

        <Section title="14. Changes to These Terms">
          <p>
            We may update these Terms from time to time. Material changes
            will be announced via email or an in-product notice at least
            14 days before they take effect. Continued use after the
            effective date constitutes acceptance of the revised Terms.
          </p>
        </Section>

        <Section title="15. Contact">
          <p>
            Questions about these Terms? Reach us at{" "}
            <a href={`mailto:${supportEmail}`} className="text-indigo-600 hover:underline">
              {supportEmail}
            </a>
            .
          </p>
        </Section>
      </main>
      <SiteFooter />
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-xl font-semibold text-slate-900 mt-8 mb-3">{title}</h2>
      <div className="text-slate-700 leading-relaxed space-y-3">{children}</div>
    </section>
  );
}
