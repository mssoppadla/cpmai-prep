"use client";
/**
 * Third-party ad tags — Google tag (Ads/GA4) + LinkedIn Insight Tag.
 *
 * Consent-first by construction: the scripts are NOT rendered until
 * the visitor has explicitly granted consent (see ConsentBanner), so
 * declining means zero third-party requests ever leave the browser.
 * Google Consent Mode v2 signals are still set (default denied →
 * granted on load) so Google's modelling behaves correctly.
 *
 * Config comes from /content/site → ads.* Runtime Settings; empty ids
 * or ads.enabled=false render nothing. Mounted once in the root
 * layout.
 */
import { useEffect, useState } from "react";
import Script from "next/script";
import { content } from "@/lib/api";
import { CONSENT_EVENT, getConsent } from "@/lib/consent";
import { setAdsConfig, type AdsConfig } from "@/lib/ads";

export function AdsScripts() {
  const [config, setConfig] = useState<AdsConfig | null>(null);
  const [consent, setConsentState] = useState<"granted" | "denied" | "unset">("unset");

  useEffect(() => {
    setConsentState(getConsent());
    const onChange = () => setConsentState(getConsent());
    window.addEventListener(CONSENT_EVENT, onChange);
    content.site()
      .then((s) => {
        const ads = (s as { ads?: AdsConfig }).ads ?? null;
        setConfig(ads);
        setAdsConfig(ads);
      })
      .catch(() => { /* no config → no tags */ });
    return () => window.removeEventListener(CONSENT_EVENT, onChange);
  }, []);

  if (!config?.enabled || consent !== "granted") return null;

  const googleOn = Boolean(config.google_tag_id);
  const linkedinOn = Boolean(config.linkedin_partner_id);
  if (!googleOn && !linkedinOn) return null;

  return (
    <>
      {googleOn && (
        <>
          <Script id="gtag-src" strategy="afterInteractive"
                  src={`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(config.google_tag_id)}`} />
          <Script id="gtag-init" strategy="afterInteractive">{`
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('consent', 'default', {
              ad_storage: 'denied', ad_user_data: 'denied',
              ad_personalization: 'denied', analytics_storage: 'denied'
            });
            gtag('consent', 'update', {
              ad_storage: 'granted', ad_user_data: 'granted',
              ad_personalization: 'granted', analytics_storage: 'granted'
            });
            gtag('js', new Date());
            gtag('config', ${JSON.stringify(config.google_tag_id)});
          `}</Script>
        </>
      )}
      {linkedinOn && (
        <Script id="linkedin-insight" strategy="afterInteractive">{`
          _linkedin_partner_id = ${JSON.stringify(config.linkedin_partner_id)};
          window._linkedin_data_partner_ids = window._linkedin_data_partner_ids || [];
          window._linkedin_data_partner_ids.push(_linkedin_partner_id);
          (function(l){
            if (!l){window.lintrk = function(a,b){window.lintrk.q.push([a,b])};
              window.lintrk.q=[];}
            var s = document.getElementsByTagName("script")[0];
            var b = document.createElement("script");
            b.type = "text/javascript"; b.async = true;
            b.src = "https://snap.licdn.com/li.lms-analytics/insight.min.js";
            s.parentNode.insertBefore(b, s);
          })(window.lintrk);
        `}</Script>
      )}
    </>
  );
}
