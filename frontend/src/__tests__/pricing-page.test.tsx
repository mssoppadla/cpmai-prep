/**
 * /pricing page behaviour:
 *   1. Renders the active plans returned by /pricing/plans.
 *   2. Calls /pricing/quote when an offer code is typed and shows the
 *      "saving ₹X" line when the server responds offer_applied=true.
 *   3. Bounces unauthenticated users to /login when "Sign in to continue"
 *      is clicked.
 *
 * Network is mocked at the global.fetch layer, the same approach used
 * by setup.tsx + page-chrome.test.tsx.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, vi, beforeEach } from "vitest";

import PricingPage from "@/app/pricing/page";

const PLAN = {
  id: 1, name: "Exam Bundle", slug: "exam-bundle",
  description: "All mock exams.", bundle_type: "exam_bundle",
  base_price_paise: 100_000, discount_price_paise: null,
  currency: "INR", duration_days: 365, perks: {}, exam_sets: [],
};

const QUOTE_NO_OFFER = {
  plan_id: 1, plan_slug: "exam-bundle", plan_name: "Exam Bundle",
  currency: "INR",
  base_price_paise: 100_000, discount_price_paise: null,
  effective_before_offer_paise: 100_000,
  offer_code: null, offer_applied: false, offer_reason: null,
  offer_discount_paise: 0,
  subtotal_paise: 100_000,
  gst_percent: 0, gst_paise: 0,
  final_price_paise: 100_000, stack_offer_with_discount: false,
};

const QUOTE_WITH_OFFER = {
  ...QUOTE_NO_OFFER,
  offer_code: "SAVE10", offer_applied: true,
  offer_reason: null, offer_discount_paise: 10_000,
  subtotal_paise: 90_000,
  final_price_paise: 90_000,
};

const QUOTE_WITH_GST = {
  ...QUOTE_NO_OFFER,
  subtotal_paise: 100_000,
  gst_percent: 18, gst_paise: 18_000,
  final_price_paise: 118_000,
};

let pushed: string[] = [];

beforeEach(() => {
  pushed = [];
});

vi.mock("next/navigation", async () => {
  const actual = await vi.importActual<typeof import("next/navigation")>("next/navigation");
  return {
    ...actual,
    useRouter: () => ({
      push: (path: string) => { pushed.push(path); },
      replace: () => {}, refresh: () => {},
    }),
    usePathname: () => "/pricing",
  };
});

function buildFetch(quoteResponse: typeof QUOTE_NO_OFFER | typeof QUOTE_WITH_OFFER) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/pricing/plans")) {
      return new Response(JSON.stringify([PLAN]), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
    if (url.endsWith("/pricing/quote")) {
      return new Response(JSON.stringify(quoteResponse), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
    if (url.endsWith("/users/me")) {
      return new Response(
        JSON.stringify({ error: { code: "unauthorized", message: "no" } }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.endsWith("/content/site")) {
      return new Response(JSON.stringify({
        brand_name: "CPMAI Prep", tagline: "", support_email: "",
        linkedin_url: "", youtube_url: "", twitter_url: "",
        copyright_text: "© 2026 CPMAI Prep. All rights reserved.",
        show_pricing_link: true,
        assistant_widget_subtitle: "",
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response("{}", {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
}


describe("/pricing page", () => {
  it("lists active plans and shows the base price", async () => {
    global.fetch = buildFetch(QUOTE_NO_OFFER);
    render(<PricingPage />);
    await waitFor(() => {
      expect(screen.getByText("Exam Bundle")).toBeInTheDocument();
    });
    // "₹1000.00" appears in both the plan card and the order summary —
    // accept any occurrence.
    await waitFor(() => {
      expect(screen.getAllByText(/₹1000\.00/).length).toBeGreaterThan(0);
    });
  });

  it("shows the offer-applied line when the server confirms it", async () => {
    global.fetch = buildFetch(QUOTE_WITH_OFFER);
    render(<PricingPage />);
    // Wait for plans to load + the offer-code input to render.
    const offerInput = await screen.findByPlaceholderText(/SAVE10/i);
    fireEvent.change(offerInput, { target: { value: "SAVE10" } });
    await waitFor(() => {
      expect(screen.getByText(/saving ₹100\.00/i)).toBeInTheDocument();
    });
  });

  it("bounces unauthenticated user to /login on checkout", async () => {
    global.fetch = buildFetch(QUOTE_NO_OFFER);
    render(<PricingPage />);
    const btn = await screen.findByRole("button", { name: /sign in to continue/i });
    fireEvent.click(btn);
    await waitFor(() => {
      expect(pushed.some(p => p.startsWith("/login"))).toBe(true);
    });
  });

  it("renders the GST line when the quote includes GST", async () => {
    global.fetch = buildFetch(QUOTE_WITH_GST);
    render(<PricingPage />);
    // Subtotal + GST(18%) + new total all show.
    await waitFor(() => {
      expect(screen.getByText("Subtotal")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText(/GST \(18%\)/)).toBeInTheDocument();
    });
    // Total should reflect the GST-inclusive amount (₹1180.00 from 100k+18k paise).
    await waitFor(() => {
      expect(screen.getAllByText(/₹1180\.00/).length).toBeGreaterThan(0);
    });
  });
});
