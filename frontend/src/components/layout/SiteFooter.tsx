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

/** Tiny social-icon row. Only renders icons whose URL is set in
 *  /admin/settings. Adding a new platform = adding one more entry
 *  here + one settings key on the backend. */
function SocialRow({ site }: { site: SiteChrome }) {
  const items = [
    site.linkedin_url && { href: site.linkedin_url, label: "LinkedIn",
      path: "M4.98 3.5C4.98 4.88 3.87 6 2.5 6S0 4.88 0 3.5 1.12 1 2.5 1s2.48 1.12 2.48 2.5zM.22 8h4.56v14H.22V8zm7.32 0h4.37v1.92h.06c.61-1.16 2.1-2.38 4.32-2.38 4.62 0 5.47 3.04 5.47 7v7.46h-4.55v-6.62c0-1.58-.03-3.62-2.21-3.62-2.21 0-2.55 1.73-2.55 3.51V22H7.54V8z" },
    site.twitter_url  && { href: site.twitter_url,  label: "Twitter / X",
      path: "M18.244 2H21l-6.52 7.45L22 22h-6.78l-4.79-6.27L4.85 22H2.09l6.97-7.97L2 2h6.93l4.36 5.76L18.244 2zm-2.39 18.18h1.69L7.4 3.74H5.6l10.254 16.44z" },
    site.youtube_url  && { href: site.youtube_url,  label: "YouTube",
      path: "M23.5 6.2a3.02 3.02 0 0 0-2.13-2.14C19.5 3.5 12 3.5 12 3.5s-7.5 0-9.37.56A3.02 3.02 0 0 0 .5 6.2C0 8.07 0 12 0 12s0 3.93.5 5.8a3.02 3.02 0 0 0 2.13 2.14C4.5 20.5 12 20.5 12 20.5s7.5 0 9.37-.56a3.02 3.02 0 0 0 2.13-2.14C24 15.93 24 12 24 12s0-3.93-.5-5.8zM9.6 15.6V8.4L15.83 12 9.6 15.6z" },
    site.instagram_url && { href: site.instagram_url, label: "Instagram",
      path: "M12 2.16c3.2 0 3.58.01 4.85.07 1.17.05 1.8.25 2.23.41.56.22.96.48 1.38.9.42.42.68.82.9 1.38.16.43.36 1.06.41 2.23.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.05 1.17-.25 1.8-.41 2.23-.22.56-.48.96-.9 1.38-.42.42-.82.68-1.38.9-.43.16-1.06.36-2.23.41-1.27.06-1.65.07-4.85.07s-3.58-.01-4.85-.07c-1.17-.05-1.8-.25-2.23-.41a3.7 3.7 0 0 1-1.38-.9 3.7 3.7 0 0 1-.9-1.38c-.16-.43-.36-1.06-.41-2.23C2.18 15.58 2.16 15.2 2.16 12s.02-3.58.08-4.85c.05-1.17.25-1.8.41-2.23.22-.56.48-.96.9-1.38.42-.42.82-.68 1.38-.9.43-.16 1.06-.36 2.23-.41C8.42 2.17 8.8 2.16 12 2.16M12 0C8.74 0 8.33.01 7.05.07 5.78.13 4.9.32 4.14.61c-.79.31-1.46.72-2.13 1.39A5.86 5.86 0 0 0 .62 4.13c-.3.76-.5 1.64-.56 2.91C0 8.33 0 8.74 0 12s.01 3.67.07 4.95c.06 1.27.25 2.15.55 2.91.31.79.72 1.46 1.39 2.13a5.86 5.86 0 0 0 2.13 1.39c.76.3 1.64.5 2.91.55C8.33 24 8.74 24 12 24s3.67-.01 4.95-.07c1.27-.06 2.15-.25 2.91-.55a5.86 5.86 0 0 0 2.13-1.39 5.86 5.86 0 0 0 1.39-2.13c.3-.76.5-1.64.55-2.91C24 15.67 24 15.26 24 12s-.01-3.67-.07-4.95c-.06-1.27-.25-2.15-.55-2.91A5.86 5.86 0 0 0 21.99 2.01 5.86 5.86 0 0 0 19.86.62c-.76-.3-1.64-.5-2.91-.56C15.67 0 15.26 0 12 0zm0 5.84a6.16 6.16 0 1 0 0 12.32 6.16 6.16 0 0 0 0-12.32zm0 10.16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.41-10.4a1.44 1.44 0 1 0 0 2.88 1.44 1.44 0 0 0 0-2.88z" },
    site.facebook_url && { href: site.facebook_url, label: "Facebook",
      path: "M22.675 0H1.325C.593 0 0 .593 0 1.326v21.348C0 23.408.593 24 1.325 24h11.495v-9.294H9.692V11.01h3.128V8.413c0-3.1 1.894-4.787 4.66-4.787 1.325 0 2.464.099 2.795.143v3.24h-1.918c-1.504 0-1.795.715-1.795 1.763v2.31h3.587l-.467 3.696h-3.12V24h6.116c.73 0 1.323-.592 1.323-1.326V1.326C24 .593 23.408 0 22.675 0z" },
    site.threads_url && { href: site.threads_url, label: "Threads",
      path: "M12.18 24h-.05c-3.07-.02-5.43-1.03-7-3.03C3.7 19.19 2.97 16.7 2.94 13.6v-.04l.01-.04c.02-3.1.75-5.6 2.17-7.39C6.7 4.13 9.06 3.12 12.13 3.1h.05c2.3.02 4.27.6 5.86 1.7 1.49 1.05 2.52 2.55 3.07 4.45l-1.96.6c-.85-2.97-3-4.66-6.06-4.68-2.55.02-4.5.77-5.79 2.31C6.02 8.89 5.4 11.1 5.4 13.6c0 2.5.6 4.7 1.91 6.13 1.29 1.55 3.24 2.3 5.79 2.31 3.05-.02 4.81-1.39 5.84-2.5 1.16-1.26 1.84-3.05 1.84-4.95 0-1.92-.7-3.62-2-4.7-.5.94-1.45 1.83-2.97 2.46-1.83.77-4.13.86-6.13.24C8.5 11.97 7.6 10.6 7.6 9c0-1.4.62-2.66 1.74-3.43 1.27-.88 3.13-1.18 5.18-.83.97.17 1.94.47 2.85.9l-.79 1.86c-1.5-.74-2.78-.95-3.83-.78-1.4.26-2.27.84-2.27 1.78 0 .85.55 1.6 1.97 1.93 1.66.4 3.43.3 4.85-.27 1.31-.5 2.05-1.32 2.27-2.48l.04-.21.13.16c1.94 1.55 3 4.07 3 6.95 0 2.36-.83 4.56-2.33 6.2-1.4 1.5-3.43 3.13-7.04 3.13z" },
    site.tiktok_url && { href: site.tiktok_url, label: "TikTok",
      path: "M19.6 6.36c-1.07-.66-1.83-1.71-2.06-2.94V3h-3.18v12.84c-.04 1.4-1.2 2.52-2.6 2.52a2.6 2.6 0 0 1-2.6-2.6 2.6 2.6 0 0 1 2.6-2.6c.27 0 .53.05.78.13v-3.24c-.26-.04-.52-.06-.78-.06A5.84 5.84 0 0 0 6 15.83a5.84 5.84 0 0 0 5.84 5.84 5.84 5.84 0 0 0 5.84-5.84V9.43c1.18.83 2.61 1.32 4.16 1.32V7.57c-1.06 0-2.05-.4-2.24-1.21z" },
    site.github_url && { href: site.github_url, label: "GitHub",
      path: "M12 .3a12 12 0 0 0-3.79 23.4c.6.11.82-.26.82-.58v-2.03c-3.34.73-4.04-1.6-4.04-1.6-.54-1.39-1.33-1.76-1.33-1.76-1.09-.74.08-.73.08-.73 1.2.09 1.84 1.24 1.84 1.24 1.07 1.84 2.81 1.3 3.5 1 .1-.78.42-1.3.76-1.6-2.66-.3-5.46-1.33-5.46-5.93 0-1.32.47-2.39 1.24-3.23-.13-.3-.54-1.53.11-3.17 0 0 1-.32 3.3 1.23a11.4 11.4 0 0 1 6 0c2.3-1.55 3.3-1.23 3.3-1.23.65 1.64.24 2.87.12 3.17.77.84 1.23 1.91 1.23 3.23 0 4.61-2.8 5.62-5.48 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.21.69.82.57A12 12 0 0 0 12 .3" },
  ].filter(Boolean) as { href: string; label: string; path: string }[];
  if (items.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-3 mt-2">
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
