/**
 * Conversion-event helpers for Google Ads + LinkedIn.
 *
 * All fire-and-forget and hard-guarded: nothing runs unless the admin
 * enabled ads, configured the relevant id, AND the visitor granted
 * consent (the tags only exist on the page post-consent — see
 * AdsScripts). A failure here must never affect checkout, so every
 * call is wrapped.
 *
 * Config arrives from /content/site (admin Runtime Settings → ads.*),
 * pushed in by AdsScripts on mount.
 */
import { getConsent } from "@/lib/consent";

export interface AdsConfig {
  enabled: boolean;
  google_tag_id: string;
  google_purchase_label: string;
  google_lead_label: string;
  linkedin_partner_id: string;
  linkedin_purchase_conversion_id: string;
  linkedin_lead_conversion_id: string;
}

let config: AdsConfig | null = null;

export function setAdsConfig(c: AdsConfig | null): void { config = c; }
export function getAdsConfig(): AdsConfig | null { return config; }

function active(): AdsConfig | null {
  if (!config?.enabled) return null;
  if (getConsent() !== "granted") return null;
  return config;
}

type GtagWindow = Window & {
  gtag?: (...args: unknown[]) => void;
  lintrk?: (action: string, data: Record<string, unknown>) => void;
};

/** Purchase conversion — call at the two payment-success points
 *  (Razorpay verify success, PayPal capture success). */
export function firePurchaseConversion(p: {
  orderId: string; amountMinor?: number; currency?: string;
}): void {
  const c = active();
  if (!c) return;
  const w = window as GtagWindow;
  try {
    if (w.gtag && c.google_tag_id && c.google_purchase_label) {
      w.gtag("event", "conversion", {
        send_to: `${c.google_tag_id}/${c.google_purchase_label}`,
        ...(typeof p.amountMinor === "number" && p.currency
          ? { value: Math.round(p.amountMinor) / 100, currency: p.currency }
          : {}),
        transaction_id: p.orderId,
      });
    }
  } catch { /* never break checkout */ }
  try {
    if (w.lintrk && c.linkedin_purchase_conversion_id) {
      w.lintrk("track",
        { conversion_id: Number(c.linkedin_purchase_conversion_id) });
    }
  } catch { /* never break checkout */ }
}

/** Lead conversion — call on successful lead-capture submission. */
export function fireLeadConversion(): void {
  const c = active();
  if (!c) return;
  const w = window as GtagWindow;
  try {
    if (w.gtag && c.google_tag_id && c.google_lead_label) {
      w.gtag("event", "conversion", {
        send_to: `${c.google_tag_id}/${c.google_lead_label}`,
      });
    }
  } catch { /* ignore */ }
  try {
    if (w.lintrk && c.linkedin_lead_conversion_id) {
      w.lintrk("track",
        { conversion_id: Number(c.linkedin_lead_conversion_id) });
    }
  } catch { /* ignore */ }
}
