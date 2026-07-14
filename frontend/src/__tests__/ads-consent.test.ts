/**
 * Consent gating for ad conversion events — the compliance contract:
 * no consent (or no config) → NOTHING fires, ever.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getConsent, setConsent } from "@/lib/consent";
import {
  fireLeadConversion, firePurchaseConversion, setAdsConfig,
} from "@/lib/ads";

const CONFIG = {
  enabled: true,
  google_tag_id: "AW-123",
  google_purchase_label: "buyLabel",
  google_lead_label: "leadLabel",
  linkedin_partner_id: "777",
  linkedin_purchase_conversion_id: "111",
  linkedin_lead_conversion_id: "222",
};

type W = Window & { gtag?: unknown; lintrk?: unknown };

describe("consent state", () => {
  afterEach(() => window.localStorage.clear());

  it("starts unset, persists a choice", () => {
    expect(getConsent()).toBe("unset");
    setConsent("granted");
    expect(getConsent()).toBe("granted");
    setConsent("denied");
    expect(getConsent()).toBe("denied");
  });
});

describe("conversion firing", () => {
  const gtag = vi.fn();
  const lintrk = vi.fn();

  beforeEach(() => {
    (window as W).gtag = gtag;
    (window as W).lintrk = lintrk;
    gtag.mockClear(); lintrk.mockClear();
    window.localStorage.clear();
  });
  afterEach(() => {
    delete (window as W).gtag;
    delete (window as W).lintrk;
    setAdsConfig(null);
  });

  it("fires purchase to both platforms when configured + consented", () => {
    setAdsConfig(CONFIG);
    setConsent("granted");
    firePurchaseConversion({ orderId: "ORD-1", amountMinor: 499900, currency: "INR" });
    expect(gtag).toHaveBeenCalledWith("event", "conversion", {
      send_to: "AW-123/buyLabel",
      value: 4999,
      currency: "INR",
      transaction_id: "ORD-1",
    });
    expect(lintrk).toHaveBeenCalledWith("track", { conversion_id: 111 });
  });

  it("omits value when amount unknown (PayPal return page)", () => {
    setAdsConfig(CONFIG);
    setConsent("granted");
    firePurchaseConversion({ orderId: "ORD-2" });
    expect(gtag).toHaveBeenCalledWith("event", "conversion", {
      send_to: "AW-123/buyLabel",
      transaction_id: "ORD-2",
    });
  });

  it("NEVER fires without consent", () => {
    setAdsConfig(CONFIG);          // configured but no consent choice
    firePurchaseConversion({ orderId: "ORD-3" });
    fireLeadConversion();
    setConsent("denied");          // explicit decline
    firePurchaseConversion({ orderId: "ORD-4" });
    expect(gtag).not.toHaveBeenCalled();
    expect(lintrk).not.toHaveBeenCalled();
  });

  it("NEVER fires when ads are disabled or unconfigured", () => {
    setConsent("granted");
    setAdsConfig({ ...CONFIG, enabled: false });
    fireLeadConversion();
    setAdsConfig(null);
    firePurchaseConversion({ orderId: "ORD-5" });
    expect(gtag).not.toHaveBeenCalled();
    expect(lintrk).not.toHaveBeenCalled();
  });

  it("lead fires with the lead label", () => {
    setAdsConfig(CONFIG);
    setConsent("granted");
    fireLeadConversion();
    expect(gtag).toHaveBeenCalledWith("event", "conversion", {
      send_to: "AW-123/leadLabel",
    });
    expect(lintrk).toHaveBeenCalledWith("track", { conversion_id: 222 });
  });
});
