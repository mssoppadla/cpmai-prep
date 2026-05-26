"use client";
/**
 * SiteHeader — unified top navigation for every public page.
 *
 *   ┌───────────────────────────────────────────────────────────┐
 *   │  CPMAI Prep   Mock Exams · FAQs · Pricing      [auth] ⌄  │
 *   └───────────────────────────────────────────────────────────┘
 *
 * Behavior:
 *   • Brand name is read from /content/site (admin-editable). Default
 *     "CPMAI Prep" if the API is unreachable.
 *   • Nav items collapse to a hamburger on screens < sm. Clicking the
 *     hamburger toggles a stacked menu below the bar.
 *   • Right side is auth-aware: shows Google sign-in or "Continue →"
 *     depending on whether /users/me succeeds. Mirrors the previous
 *     LandingTopBar logic so the landing page UX is unchanged.
 *   • The `active` prop highlights the matching nav item.
 *
 * Renders a placeholder for the auth area while the /me probe is in
 * flight, so we never flash the wrong state. The rest of the bar is
 * static and shows immediately.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { auth, cmsPublic, content as contentApi } from "@/lib/api";
import { GoogleSignInButton } from "@/lib/google-auth";
import type {
  ContentPageNavItemOut,
  SiteChrome,
  UserOut,
} from "@/types/api";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";

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
  // Empty default — when /content/site returns the seeded list, the
  // assistant widget renders the suggestions as clickable chips. The
  // header itself doesn't consume this; it's just here to satisfy the
  // SiteChrome type so the AssistantWidget can pull it from the same
  // already-fetched payload.
  assistant_try_asking_suggestions: [],
  assistant_anonymous_no_identity_message:
    "Please sign in to continue chatting. Anonymous chat needs a " +
    "browser identifier — refresh the page or sign in.",
};

function destinationFor(role: UserOut["role"]): string {
  return role === "admin" || role === "super_admin" ? "/admin" : "/dashboard";
}

export type ActiveNav = "home" | "exams" | "faqs" | "pricing" | null;

export function SiteHeader({ active = null }: { active?: ActiveNav }) {
  const router = useRouter();
  const [me, setMe] = useState<UserOut | null | undefined>(undefined);
  const [site, setSite] = useState<SiteChrome>(SITE_FALLBACK);
  const [cmsNav, setCmsNav] = useState<ContentPageNavItemOut[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    contentApi.site().then((s) => { if (!cancelled) setSite(s); }).catch(() => {});
    // Public CMS nav — empty array on any failure so the header still
    // renders cleanly without published CMS pages. Re-fetched when the
    // user logs in (the visibility filter widens for authenticated /
    // subscribed tiers — see backend nav_query.py).
    cmsPublic.nav().then((items) => {
      if (!cancelled) setCmsNav(items);
    }).catch(() => {});
    (async () => {
      try {
        const u = await auth.me();
        if (!cancelled) setMe(u);
        // After login the user's visibility tier may have widened —
        // re-fetch the nav so authenticated/subscribed pages appear.
        try {
          const items = await cmsPublic.nav();
          if (!cancelled) setCmsNav(items);
        } catch {}
      } catch {
        const ok = await auth.refresh();
        if (cancelled) return;
        if (!ok) { setMe(null); return; }
        try { setMe(await auth.me()); } catch { setMe(null); }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  async function handleGoogle(credential: string) {
    try {
      const tokens = await auth.googleLogin(credential);
      router.push(destinationFor(tokens.user.role));
    } catch {
      router.push("/login");
    }
  }

  // Active-style for nav links.
  const navLink = (key: ActiveNav, href: string, label: string) => {
    const isActive = active === key;
    return (
      <Link
        href={href}
        onClick={() => setMenuOpen(false)}
        className={
          "px-3 py-2 text-sm rounded-md transition " +
          (isActive
            ? "text-indigo-700 bg-indigo-50 font-semibold"
            : "text-slate-700 hover:text-indigo-600 hover:bg-slate-50")
        }
      >
        {label}
      </Link>
    );
  };

  return (
    <header className="border-b border-slate-200 bg-white/80 backdrop-blur supports-[backdrop-filter]:bg-white/70 sticky top-0 z-30">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-3 flex items-center gap-4">
        {/* Brand */}
        <Link
          href="/"
          className="font-bold text-slate-900 text-base sm:text-lg whitespace-nowrap"
        >
          {site.brand_name}
        </Link>

        {/* Nav — desktop. Static items first, then any CMS-published
         *  nav items in admin-defined order. */}
        <nav className="hidden sm:flex items-center gap-1 ml-2">
          {navLink("exams", "/exams", "Mock Exams")}
          {navLink("faqs",  "/#faq-heading", "FAQs")}
          {site.show_pricing_link &&
            navLink("pricing", "/pricing", "Pricing")}
          {cmsNav.map((item) => (
            <Link
              key={item.slug}
              href={`/pages/${item.slug}`}
              onClick={() => setMenuOpen(false)}
              className="px-3 py-2 text-sm rounded-md transition text-slate-700 hover:text-indigo-600 hover:bg-slate-50"
            >
              {item.label}
            </Link>
          ))}
        </nav>

        {/* Spacer pushes auth area to the right */}
        <div className="flex-1" />

        {/* Auth area */}
        <div className="flex items-center gap-2 sm:gap-3">
          {me === undefined ? (
            <div className="h-9 w-28 bg-slate-100 rounded animate-pulse" aria-hidden />
          ) : me ? (
            <>
              <span className="hidden md:inline text-sm text-slate-600 truncate max-w-[180px]">
                {me.email}
              </span>
              <Link
                href={destinationFor(me.role)}
                className="px-3 sm:px-4 py-2 bg-indigo-600 text-white text-xs sm:text-sm font-semibold rounded-lg hover:bg-indigo-700"
              >
                {me.role === "admin" || me.role === "super_admin"
                  ? "Admin →"
                  : "Dashboard →"}
              </Link>
            </>
          ) : (
            <>
              {GOOGLE_CLIENT_ID && (
                <div className="hidden sm:block">
                  <GoogleSignInButton
                    clientId={GOOGLE_CLIENT_ID}
                    onCredential={handleGoogle}
                    buttonConfig={{ size: "medium", text: "signin_with" }}
                  />
                </div>
              )}
              <Link
                href="/login"
                data-track="cta:sign_in_header"
                className="text-xs sm:text-sm text-slate-700 hover:text-indigo-600 px-3 py-2 border border-slate-300 rounded-lg hover:bg-slate-50"
              >
                Sign in
              </Link>
            </>
          )}

          {/* Hamburger — mobile only */}
          <button
            type="button"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
            className="sm:hidden p-2 text-slate-700 hover:bg-slate-100 rounded-md"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              {menuOpen ? (
                <>
                  <line x1="6" y1="6" x2="18" y2="18" />
                  <line x1="6" y1="18" x2="18" y2="6" />
                </>
              ) : (
                <>
                  <line x1="4" y1="7"  x2="20" y2="7"  />
                  <line x1="4" y1="12" x2="20" y2="12" />
                  <line x1="4" y1="17" x2="20" y2="17" />
                </>
              )}
            </svg>
          </button>
        </div>
      </div>

      {/* Mobile dropdown menu */}
      {menuOpen && (
        <div className="sm:hidden border-t border-slate-200 bg-white">
          <nav className="max-w-6xl mx-auto px-4 py-2 flex flex-col gap-1">
            {navLink("exams", "/exams", "Mock Exams")}
            {navLink("faqs",  "/#faq-heading", "FAQs")}
            {site.show_pricing_link &&
              navLink("pricing", "/pricing", "Pricing")}
            {cmsNav.map((item) => (
              <Link
                key={item.slug}
                href={`/pages/${item.slug}`}
                onClick={() => setMenuOpen(false)}
                className="px-3 py-2 text-sm rounded-md text-slate-700 hover:text-indigo-600 hover:bg-slate-50"
              >
                {item.label}
              </Link>
            ))}
            {!me && GOOGLE_CLIENT_ID && (
              <div className="py-2 px-3">
                <GoogleSignInButton
                  clientId={GOOGLE_CLIENT_ID}
                  onCredential={handleGoogle}
                  buttonConfig={{ size: "medium", text: "signin_with" }}
                />
              </div>
            )}
          </nav>
        </div>
      )}
    </header>
  );
}
