/**
 * Custom 404 — replaces Next's bare default with branded, ADMIN-EDITABLE
 * copy (errors.not_found_* in /admin/settings). The help-links block
 * (quick links + the live-class registration button) is toggled by
 * errors.show_help_links; when the landing banner is enabled and has a
 * registration URL, that link rides along here too so a lost visitor
 * can still reach the live classes.
 *
 * Fetches fresh on every render (no-store) so admin edits show up
 * immediately; falls back to the seeded defaults if the API is down —
 * a 404 page must never itself crash.
 */
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { HELP_LINKS } from "@/lib/help-links";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

const FALLBACK_COPY = {
  not_found_title: "Uh oh! You seem to have lost your way.",
  not_found_body: "Let us help you find what you were looking for:",
  show_help_links: true,
};

async function fetchJson<T extends object>(path: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(`${API}${path}`, { cache: "no-store" });
    if (!r.ok) return fallback;
    const data = await r.json();
    // Defensive: a 404 page must render even if the API returns
    // garbage (arrays, null, wrong shape) — merge over the fallback so
    // missing fields keep their defaults.
    if (data && typeof data === "object" && !Array.isArray(data)) {
      return { ...fallback, ...data };
    }
    return fallback;
  } catch {
    return fallback;
  }
}

export default async function NotFound() {
  const [copy, landing] = await Promise.all([
    fetchJson<typeof FALLBACK_COPY>("/content/errors", FALLBACK_COPY),
    fetchJson<{ live_banner_enabled?: boolean; live_banner_link_url?: string;
                live_banner_link_label?: string }>("/content/landing", {}),
  ]);
  const showRegistration = Boolean(
    copy.show_help_links && landing.live_banner_enabled && landing.live_banner_link_url);

  return (
    <>
      <SiteHeader active="home" />
      <main className="min-h-screen">
        <div className="max-w-2xl mx-auto px-4 sm:px-6 pt-20 sm:pt-28 pb-24 text-center">
          <div aria-hidden className="text-6xl sm:text-7xl font-bold text-indigo-100 select-none">
            404
          </div>
          <h1 className="mt-4 text-2xl sm:text-3xl font-bold text-slate-900 text-balance">
            {copy.not_found_title}
          </h1>
          {copy.not_found_body && (
            <p className="mt-3 text-slate-600">{copy.not_found_body}</p>
          )}

          {copy.show_help_links && (
            <div className="mt-8 flex flex-wrap justify-center gap-3">
              {HELP_LINKS.map(l => (
                <Link key={l.href} href={l.href}
                      className="px-4 py-2 rounded-lg border border-slate-300 bg-white
                                 text-sm font-medium text-slate-700 hover:border-indigo-300
                                 hover:text-indigo-700 transition">
                  {l.label}
                </Link>
              ))}
              {showRegistration && (
                <a href={landing.live_banner_link_url}
                   target="_blank" rel="noopener noreferrer"
                   data-track="cta:live_class_register_404"
                   className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm
                              font-semibold hover:bg-indigo-700 transition
                              inline-flex items-center gap-1.5">
                  {landing.live_banner_link_label || "Register for live classes"}
                  <ExternalLink size={14} />
                </a>
              )}
            </div>
          )}
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
