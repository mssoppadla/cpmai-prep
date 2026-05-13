"use client";
/**
 * SiteFooter — site-wide footer used on every public page.
 *
 *   Brand + tagline   |  Product   |  Resources   |  Legal
 *   ─────────────────────────────────────────────────────
 *               © copyright text · social icons
 *
 * All visible copy + social URLs are admin-editable via /admin/settings
 * (the `site.*` keys). Empty values hide the corresponding row/icon so
 * admins can progressively reveal channels.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { content as contentApi } from "@/lib/api";
import type { SiteChrome } from "@/types/api";

const SITE_FALLBACK: SiteChrome = {
  brand_name: "CPMAI Prep",
  tagline: "Pass the CPMAI certification on your first attempt.",
  support_email: "",
  linkedin_url: "",
  youtube_url: "",
  twitter_url: "",
  copyright_text: "© 2026 CPMAI Prep. All rights reserved.",
  show_pricing_link: true,
  assistant_widget_subtitle: "Grounded in our FAQ, pricing & question explanations",
  // Empty default — backend sends the seeded list. Footer never reads
  // this anyway, but TypeScript requires the field to be present.
  assistant_try_asking_suggestions: [],
  assistant_anonymous_no_identity_message:
    "Please sign in to continue chatting. Anonymous chat needs a " +
    "browser identifier — refresh the page or sign in.",
};

export function SiteFooter() {
  const [site, setSite] = useState<SiteChrome>(SITE_FALLBACK);

  useEffect(() => {
    let cancelled = false;
    contentApi.site().then((s) => { if (!cancelled) setSite(s); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  return (
    <footer className="mt-16 border-t border-slate-200 bg-white">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-10 grid gap-8 md:grid-cols-4">
        {/* Brand + tagline */}
        <div className="md:col-span-1">
          <div className="font-bold text-slate-900 text-lg">{site.brand_name}</div>
          {site.tagline && (
            <p className="mt-2 text-sm text-slate-600 leading-relaxed">
              {site.tagline}
            </p>
          )}
        </div>

        {/* Product */}
        <FooterCol title="Product">
          <FooterLink href="/exams">Mock Exams</FooterLink>
          {site.show_pricing_link && <FooterLink href="/pricing">Pricing</FooterLink>}
          <FooterLink href="/#faq-heading">FAQs</FooterLink>
        </FooterCol>

        {/* Resources */}
        <FooterCol title="Resources">
          <FooterLink href="/#study-guide">Free study guide</FooterLink>
          <FooterLink href="/dashboard">Your dashboard</FooterLink>
          {site.support_email && (
            <a
              href={`mailto:${site.support_email}`}
              className="text-sm text-slate-600 hover:text-indigo-600"
            >
              Email support
            </a>
          )}
        </FooterCol>

        {/* Legal + social */}
        <FooterCol title="Legal">
          <FooterLink href="/privacy">Privacy</FooterLink>
          <FooterLink href="/terms">Terms</FooterLink>
          <SocialRow site={site} />
        </FooterCol>
      </div>

      <div className="border-t border-slate-200">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 text-xs text-slate-500 text-center sm:text-left">
          {site.copyright_text}
        </div>
      </div>
    </footer>
  );
}

function FooterCol({ title, children }: {
  title: string; children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
        {title}
      </div>
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  );
}

function FooterLink({ href, children }: {
  href: string; children: React.ReactNode;
}) {
  return (
    <Link href={href} className="text-sm text-slate-600 hover:text-indigo-600">
      {children}
    </Link>
  );
}

/** Tiny social-icon row. Only renders icons whose URL is set. */
function SocialRow({ site }: { site: SiteChrome }) {
  const items = [
    site.linkedin_url && { href: site.linkedin_url, label: "LinkedIn", path: "M4.98 3.5C4.98 4.88 3.87 6 2.5 6S0 4.88 0 3.5 1.12 1 2.5 1s2.48 1.12 2.48 2.5zM.22 8h4.56v14H.22V8zm7.32 0h4.37v1.92h.06c.61-1.16 2.1-2.38 4.32-2.38 4.62 0 5.47 3.04 5.47 7v7.46h-4.55v-6.62c0-1.58-.03-3.62-2.21-3.62-2.21 0-2.55 1.73-2.55 3.51V22H7.54V8z" },
    site.twitter_url  && { href: site.twitter_url,  label: "Twitter / X",
      path: "M18.244 2H21l-6.52 7.45L22 22h-6.78l-4.79-6.27L4.85 22H2.09l6.97-7.97L2 2h6.93l4.36 5.76L18.244 2zm-2.39 18.18h1.69L7.4 3.74H5.6l10.254 16.44z" },
    site.youtube_url  && { href: site.youtube_url,  label: "YouTube",
      path: "M23.5 6.2a3.02 3.02 0 0 0-2.13-2.14C19.5 3.5 12 3.5 12 3.5s-7.5 0-9.37.56A3.02 3.02 0 0 0 .5 6.2C0 8.07 0 12 0 12s0 3.93.5 5.8a3.02 3.02 0 0 0 2.13 2.14C4.5 20.5 12 20.5 12 20.5s7.5 0 9.37-.56a3.02 3.02 0 0 0 2.13-2.14C24 15.93 24 12 24 12s0-3.93-.5-5.8zM9.6 15.6V8.4L15.83 12 9.6 15.6z" },
  ].filter(Boolean) as { href: string; label: string; path: string }[];
  if (items.length === 0) return null;
  return (
    <div className="flex gap-3 mt-2">
      {items.map((it) => (
        <a key={it.label} href={it.href} aria-label={it.label}
           target="_blank" rel="noopener noreferrer"
           className="text-slate-500 hover:text-indigo-600">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d={it.path} />
          </svg>
        </a>
      ))}
    </div>
  );
}
