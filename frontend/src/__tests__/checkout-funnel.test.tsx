/**
 * Checkout Follow-ups page — renders the two follow-up lists with
 * contact links, and the empty states, from the /admin/checkout-funnel
 * payload.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { CheckoutFunnelOut } from "@/lib/api";

const mockGet = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...orig,
    admin: {
      ...orig.admin,
      checkoutFunnel: { get: (...a: unknown[]) => mockGet(...a) },
    },
  };
});

import CheckoutFunnelPage from "@/app/admin/checkout-funnel/page";

const PAYLOAD: CheckoutFunnelOut = {
  window_minutes: 1440,
  since: "2026-08-16T00:00:00Z",
  needs_followup: [{
    payment_id: 7, status: "failed", provider_order_id: "ord_1",
    plan_name: "Full Prep", amount_paise: 499900, currency: "INR",
    created_at: "2026-08-16T05:00:00Z",
    user: { id: 3, email: "buyer@example.com", name: "Buyer B",
            whatsapp: "+91 9876543210", linkedin_id: "buyer-b" },
  }],
  pricing_visitors: [{
    user: null, anon_id: "anon-xyz-99887766", last_seen_at: "2026-08-16T06:00:00Z",
    country: "US", city: "Austin", device: "desktop", utm_source: "linkedin",
  }],
  summary: { visitors: 5, started: 2, captured: 1, needs_followup: 1 },
};

beforeEach(() => { mockGet.mockReset(); });

describe("CheckoutFunnelPage", () => {
  it("renders follow-up row with contact links (mailto + wa.me + linkedin)", async () => {
    mockGet.mockResolvedValue(PAYLOAD);
    render(<CheckoutFunnelPage />);
    await waitFor(() => expect(screen.getByText("Buyer B")).toBeInTheDocument());

    expect(screen.getByRole("link", { name: "buyer@example.com" }))
      .toHaveAttribute("href", "mailto:buyer@example.com");
    expect(screen.getByRole("link", { name: "WhatsApp" }))
      .toHaveAttribute("href", "https://wa.me/919876543210");
    expect(screen.getByRole("link", { name: "LinkedIn" }))
      .toHaveAttribute("href", expect.stringContaining("linkedin.com/in/buyer-b"));
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("₹4999.00")).toBeInTheDocument();
  });

  it("renders anonymous pricing visitor with location + summary counts", async () => {
    mockGet.mockResolvedValue(PAYLOAD);
    render(<CheckoutFunnelPage />);
    await waitFor(() => expect(screen.getByText(/anon-xyz/)).toBeInTheDocument());
    expect(screen.getByText("Austin, US")).toBeInTheDocument();
    // Summary cards
    expect(screen.getByText("Pricing visitors").previousSibling).toHaveTextContent("5");
    expect(screen.getByText("Need follow-up").previousSibling).toHaveTextContent("1");
  });

  it("renders friendly empty states", async () => {
    mockGet.mockResolvedValue({
      ...PAYLOAD, needs_followup: [], pricing_visitors: [],
      summary: { visitors: 0, started: 0, captured: 0, needs_followup: 0 },
    });
    render(<CheckoutFunnelPage />);
    await waitFor(() =>
      expect(screen.getByText(/Nothing needs follow-up/)).toBeInTheDocument());
    expect(screen.getByText(/No pricing visitors without checkout/)).toBeInTheDocument();
  });
});
