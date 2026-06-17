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
import { SocialLinks } from "@/components/layout/SocialLinks";

const SITE_FALLBACK: SiteChrome = {
  brand_name: "CPMAI Prep",
  tagline: "Pass the CPMAI certification on your first attempt.",
  support_email: "",
  privacy_email: "",
  contact_phone: "",
  linkedin_url: "",
  youtube_url: "",
  twitter_url: "",
  instagram_url: "",
  facebook_url: "",
  threads_url: "",
  tiktok_url: "",
  github_url: "",
  reddit_url: "",
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
          <SocialLinks site={site} className="mt-2" />
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
