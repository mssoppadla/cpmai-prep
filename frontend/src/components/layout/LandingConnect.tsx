/**
 * LandingConnect — "connect with me" block shown below the landing-page
 * lead-capture CTA. Renders an admin-configurable heading plus the social
 * icons whose URLs are set in /admin/settings (LinkedIn, Reddit, …).
 *
 * Renders NOTHING when no social URLs are configured, so the section
 * stays invisible until the operator fills in at least one link. Pure
 * markup (no hooks) → safe to render from the server component.
 */
import type { SiteChrome } from "@/types/api";
import { SocialLinks, socialItems } from "@/components/layout/SocialLinks";

export function LandingConnect({ site, heading }: {
  site: Partial<SiteChrome>;
  heading: string;
}) {
  if (socialItems(site).length === 0) return null;
  return (
    <section
      aria-label="Connect"
      className="max-w-md mx-auto px-4 sm:px-6 pb-16 sm:pb-20 -mt-8 sm:-mt-12 text-center"
    >
      {heading && (
        <p className="text-sm font-medium text-slate-600 mb-3">{heading}</p>
      )}
      <SocialLinks site={site} className="justify-center" />
    </section>
  );
}
