"use client";
/**
 * Cookie-consent banner — shown only when ad tags are configured AND
 * the visitor hasn't chosen yet. Decline (or ignoring the banner)
 * means the third-party tags never load; our first-party analytics is
 * unaffected either way and is disclosed in the privacy policy.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { content } from "@/lib/api";
import { getConsent, setConsent } from "@/lib/consent";
import type { AdsConfig } from "@/lib/ads";

export function ConsentBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (getConsent() !== "unset") return;
    content.site()
      .then((s) => {
        const ads = (s as { ads?: AdsConfig }).ads;
        const configured = Boolean(ads?.enabled
          && (ads.google_tag_id || ads.linkedin_partner_id));
        if (configured) setVisible(true);
      })
      .catch(() => { /* no config — no banner */ });
  }, []);

  if (!visible) return null;

  function choose(v: "granted" | "denied") {
    setConsent(v);
    setVisible(false);
  }

  return (
    <div role="dialog" aria-label="Cookie consent"
         className="fixed bottom-0 inset-x-0 z-50 bg-white border-t border-slate-200
                    shadow-[0_-4px_20px_rgba(0,0,0,0.08)] p-4">
      <div className="max-w-4xl mx-auto flex flex-col sm:flex-row sm:items-center gap-3">
        <p className="flex-1 text-sm text-slate-700">
          We&rsquo;d like to use advertising cookies (Google, LinkedIn) to measure
          our campaigns and show relevant ads. No advertising cookies are set
          unless you accept. See our{" "}
          <Link href="/privacy" className="text-indigo-600 hover:underline">
            Privacy Policy
          </Link>.
        </p>
        <div className="flex gap-2 flex-shrink-0">
          <button onClick={() => choose("denied")}
                  className="px-4 py-2 text-sm font-medium text-slate-700 bg-white
                             border border-slate-300 rounded-lg hover:bg-slate-50">
            Decline
          </button>
          <button onClick={() => choose("granted")}
                  className="px-4 py-2 text-sm font-semibold text-white bg-indigo-600
                             rounded-lg hover:bg-indigo-700">
            Accept
          </button>
        </div>
      </div>
    </div>
  );
}
