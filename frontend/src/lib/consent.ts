/**
 * Cookie-consent state for third-party ad tags (Google Ads, LinkedIn).
 *
 * Stored in localStorage; "unset" until the visitor chooses. The ad
 * scripts load ONLY after "granted" (see components/ads/AdsScripts) —
 * decline or no-choice means zero third-party requests, matching the
 * privacy policy's consent-first promise. First-party analytics (our
 * own tracker) is unaffected by this state.
 */
export type ConsentState = "granted" | "denied" | "unset";

const KEY = "cpmai.ads_consent";
export const CONSENT_EVENT = "cpmai:consent-changed";

export function getConsent(): ConsentState {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "granted" || v === "denied" ? v : "unset";
  } catch {
    return "unset";   // storage blocked → treat as no consent
  }
}

export function setConsent(v: "granted" | "denied"): void {
  try {
    window.localStorage.setItem(KEY, v);
  } catch { /* storage blocked — state stays per-page */ }
  window.dispatchEvent(new CustomEvent(CONSENT_EVENT, { detail: v }));
}
