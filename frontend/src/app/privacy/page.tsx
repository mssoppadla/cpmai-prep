/**
 * /privacy — Privacy Policy page.
 *
 * Mirrors the structure of /terms (see that file's header for the
 * rationale on server-component + when to migrate to CMS).
 *
 * Reflects the actual data-handling practices visible in this codebase
 * as of 2026-05-21 — GeoIP enrichment, chat logging, audit logs,
 * payment processing through Razorpay, encryption at rest for
 * credentials. Update when behaviour changes.
 */
import type { Metadata } from "next";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import type { SiteChrome } from "@/types/api";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "How CPMAI Prep collects, uses and protects your personal data.",
  alternates: { canonical: "/privacy" },
};

const LAST_UPDATED = "2026-05-26";

async function getChrome(): Promise<Partial<SiteChrome>> {
  try {
    const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
    // Hard 5s timeout via AbortSignal — without it, the static-page
    // build hangs for the full 60s Next.js static-worker deadline
    // when no backend is reachable (e.g. local prod builds, sandboxed
    // CI runners without a backend service). The empty-chrome
    // fallback below still renders a usable page, so failing fast is
    // strictly better than blowing the build.
    const r = await fetch(`${base}/content/site`, {
      next: { revalidate: 300 },
      signal: AbortSignal.timeout(5000),
    });
    if (!r.ok) return {};
    return await r.json();
  } catch {
    return {};
  }
}


export default async function PrivacyPage() {
  const chrome = await getChrome();
  // privacy_email falls back to support_email server-side. Final
  // frontend fallback to a placeholder so the page renders even if
  // both are unconfigured.
  const privacyEmail = chrome.privacy_email || chrome.support_email
    || "privacy@cpmaiexamprep.com";
  return (
    <>
      <SiteHeader />
      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-12 prose prose-slate">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Privacy Policy</h1>
        <p className="text-sm text-slate-500 mb-8">Last updated: {LAST_UPDATED}</p>

        <Section title="1. Overview">
          <p>
            This Privacy Policy explains what personal information CPMAI
            Prep (the &ldquo;Service&rdquo;) collects, how we use it, who we share
            it with, and the choices you have. We aim to collect the
            minimum necessary to operate the Service well.
          </p>
        </Section>

        <Section title="2. Information We Collect">
          <h3 className="text-base font-semibold text-slate-800 mt-4 mb-2">
            You provide directly
          </h3>
          <ul>
            <li>Name, email address, and password when you register</li>
            <li>Phone number and WhatsApp number when you opt to share these (e.g. through a callback request)</li>
            <li>Payment instrument details — handled directly by Razorpay; we never see or store your full card number or UPI VPA</li>
            <li>Profile data you choose to add (company, role, study notes)</li>
            <li>Content of chat conversations with our AI assistant and any feedback you submit</li>
          </ul>

          <h3 className="text-base font-semibold text-slate-800 mt-4 mb-2">
            Collected automatically
          </h3>
          <ul>
            <li>IP address and approximate location (country, city) derived via MaxMind GeoIP — used for currency selection, fraud mitigation and country-specific tax handling</li>
            <li>Device, browser and OS information visible in standard HTTP headers</li>
            <li>Pages visited, course progress, quiz attempts and timestamps</li>
            <li>Anonymous-session identifiers stored as cookies to maintain pre-login activity</li>
          </ul>
        </Section>

        <Section title="3. How We Use Your Information">
          <ul>
            <li><strong>Provide the Service</strong>: authenticate you, track course progress, deliver content, process payments</li>
            <li><strong>Personalise</strong>: surface relevant courses, default to your local currency, remember in-progress lessons</li>
            <li><strong>Communicate</strong>: send transactional emails (receipts, account notices), respond to support requests, send course/session reminders</li>
            <li><strong>Improve</strong>: review aggregated usage patterns and AI conversation quality to fix bugs and improve teaching content</li>
            <li><strong>Comply with law</strong>: retain financial records (typically 7 years under Indian tax law), respond to lawful requests</li>
            <li><strong>Security</strong>: detect abuse, rate-limit, audit-log administrator actions</li>
          </ul>
        </Section>

        <Section title="4. Sharing Your Information">
          <p>
            We do not sell your personal data. We share information only
            with the following parties, and only for the purposes
            described:
          </p>
          <ul>
            <li><strong>Payment processors</strong> (Razorpay, PayPal where applicable) — for processing transactions</li>
            <li><strong>Email delivery</strong> (Resend / Postmark / equivalent) — to send the emails listed above</li>
            <li><strong>Cloud infrastructure</strong> (our hosting provider, Cloudflare for asset delivery) — to operate the Service</li>
            <li><strong>AI providers</strong> (OpenAI, Anthropic where configured) — to generate answers in the AI assistant. Conversation contents are sent to these providers as part of normal operation. We pass through their own data-handling commitments and do not use your data for model training</li>
            <li><strong>Live-session providers</strong> (Zoom) — to host video sessions where applicable</li>
            <li><strong>Legal compliance</strong> — when required by law or to protect rights, property or safety</li>
          </ul>
        </Section>

        <Section title="5. Cookies and Local Storage">
          <p>
            We use cookies and browser local storage for:
          </p>
          <ul>
            <li>Authentication (an access token and a refresh token)</li>
            <li>Maintaining anonymous-session state before sign-up</li>
            <li>Remembering UI preferences (e.g. sidebar collapsed state)</li>
          </ul>
          <p>
            We do not use third-party advertising cookies. You may
            disable cookies in your browser, but doing so will prevent
            you from logging in.
          </p>
        </Section>

        <Section title="5a. Product Analytics (Visitor Insights)">
          <p>
            To understand how visitors and learners use the Service, we
            run a first-party analytics tracker (no third-party
            analytics provider, no cross-site tracking). This tracker
            runs only in your browser session on our domain and the
            data is stored on our own infrastructure.
          </p>
          <p><strong>What we collect:</strong></p>
          <ul>
            <li>The pages you view on this Service and the timestamps</li>
            <li>How long each page was actively in the foreground (the tracker pauses when the tab is in the background)</li>
            <li>Scroll depth on each page (25 / 50 / 75 / 100% milestones), to identify which content learners actually read</li>
            <li>Clicks on a small number of explicitly-tagged calls-to-action (sign in, plan select, checkout, request callback, course enrol) — we do NOT capture every click</li>
            <li>Standard UTM parameters in the URL if you arrived via a tagged campaign link</li>
            <li>Referrer URL (the page that linked you here) with personal-looking query parameters (email, phone, tokens) stripped server-side before storage</li>
            <li>Device, browser and operating system bucket parsed from the standard User-Agent header</li>
            <li>Country and city from the same MaxMind GeoIP lookup described in §2 — not the precise IP</li>
          </ul>
          <p><strong>Why:</strong> improving the product (finding pages that aren&apos;t working), measuring whether new features are used, identifying drop-off in the signup &rarr; payment flow.</p>
          <p><strong>How to opt out:</strong></p>
          <ul>
            <li>The tracker honours your browser&apos;s <em>Do Not Track</em> setting (set <code>navigator.doNotTrack = &quot;1&quot;</code> via your browser&apos;s privacy settings).</li>
            <li>Operators can disable the tracker globally via a server-side kill switch; we may use this during incidents or in response to specific user requests.</li>
            <li>You may request your captured analytics rows be detached from your identity at any time via the data deletion flow in §8 — your aggregate event counts stay in place, but no further drilldown by your visitor identifier is possible.</li>
          </ul>
          <p>
            Retention for analytics events follows the same schedule as
            other usage data (see §7).
          </p>
        </Section>

        <Section title="6. Data Security">
          <p>
            We use TLS encryption for data in transit. Sensitive
            credentials (API keys, payment-provider secrets) stored
            server-side are encrypted at rest. Passwords are stored
            using salted hashing — never in plaintext. Access to
            production data is restricted to authorised personnel and
            audit-logged.
          </p>
          <p>
            No system can be 100% secure. We will notify affected users
            promptly in the event of a confirmed personal-data breach
            in compliance with applicable law.
          </p>
        </Section>

        <Section title="7. Data Retention">
          <p>
            We retain your data for as long as your account is active,
            plus the periods needed for the purposes described in this
            policy. After account deletion:
          </p>
          <ul>
            <li>Personally-identifying fields (email, name, Google ID) are redacted within 24 hours</li>
            <li>Your account is marked inactive and you can no longer sign in</li>
            <li>Financial records (invoices, payment confirmations) are retained for 7 years to comply with Indian tax and accounting law</li>
            <li>Aggregated, non-identifying usage analytics may be retained indefinitely</li>
          </ul>
        </Section>

        <Section title="8. Your Rights">
          <p>You have the right to:</p>
          <ul>
            <li><strong>Access</strong> — download a copy of your data (export from account settings)</li>
            <li><strong>Correct</strong> — fix inaccurate information in your account</li>
            <li><strong>Delete</strong> — request deletion of your account and the redaction of identifying data (subject to the legal-retention requirements in Section 7)</li>
            <li><strong>Opt out</strong> of marketing communications (we send only transactional ones by default)</li>
            <li><strong>Withdraw consent</strong> at any time where processing relies on consent</li>
          </ul>
          <p>
            Exercise these rights through your account settings, or by
            emailing us at{" "}
            <a href={`mailto:${privacyEmail}`} className="text-indigo-600 hover:underline">
              {privacyEmail}
            </a>
            . We respond within 30 days.
          </p>
        </Section>

        <Section title="9. Children's Privacy">
          <p>
            The Service is not directed at children under 18. If we
            learn that we have inadvertently collected data from a minor,
            we will delete it promptly.
          </p>
        </Section>

        <Section title="10. International Transfers">
          <p>
            Our infrastructure is hosted primarily in India. Some of our
            sub-processors (e.g. OpenAI, Cloudflare) operate outside
            India. We rely on those vendors&apos; published security and
            privacy commitments to safeguard data in transit.
          </p>
        </Section>

        <Section title="11. Changes to This Policy">
          <p>
            We may update this Privacy Policy from time to time.
            Material changes will be announced via email or an in-product
            notice at least 14 days before they take effect. The
            &ldquo;Last updated&rdquo; date above always reflects the
            current version.
          </p>
        </Section>

        <Section title="12. Contact">
          <p>
            For privacy questions, data-rights requests, or breach
            notifications, reach us at{" "}
            <a href={`mailto:${privacyEmail}`} className="text-indigo-600 hover:underline">
              {privacyEmail}
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
