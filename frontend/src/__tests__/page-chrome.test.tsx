/**
 * Per-page chrome smoke — verifies SiteHeader and SiteFooter render on
 * every public page that should have them. Keeps the unified-chrome
 * promise honest: any future page that drops the wrappers fails the
 * gate.
 *
 * Each test:
 *   1. Renders the page component (with whatever async state a page
 *      typically lands in — usually "loading" because the page calls
 *      auth.me() which our setup stubs to return 401)
 *   2. Asserts the brand name (header) AND copyright text (footer)
 *      are present in the DOM
 *
 * Tests are intentionally shallow — we're not checking page-specific
 * functionality here, only that header/footer render. Page-specific
 * behavior belongs in dedicated test files.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, vi } from "vitest";

// Pull in the pages — the mocks set up in setup.tsx (next/link,
// next/navigation, fetch) make these renderable in jsdom.
import LandingPage from "@/app/page";
import LoginPage from "@/app/login/page";
import LearnerDashboard from "@/app/(app)/dashboard/page";
import ExamSetsListPage from "@/app/(app)/exams/page";
import ResultsPage from "@/app/(app)/exams/results/[id]/page";
import PricingPage from "@/app/pricing/page";
import PublicContentPage from "@/app/pages/[slug]/page";

const BRAND = "CPMAI Prep";
const COPY = "© 2026 CPMAI Prep. All rights reserved.";

async function expectHeaderAndFooter() {
  // Header brand and footer copyright both come from /content/site
  // (mocked in setup.tsx). Wait for the async fetch+setState to settle.
  await waitFor(() => {
    // The brand appears in BOTH header (link) and footer (text). At least
    // one occurrence is enough to confirm SiteHeader rendered.
    expect(screen.getAllByText(BRAND).length).toBeGreaterThan(0);
  });
  await waitFor(() => {
    expect(screen.getByText(COPY)).toBeInTheDocument();
  });
}

describe("page chrome — every public page wraps SiteHeader + SiteFooter", () => {
  it("/ (landing)", async () => {
    // Landing is an async server-component-style export with await
    // inside. Calling it returns a Promise<JSX>; resolve before render.
    const ui = await LandingPage();
    render(ui);
    await expectHeaderAndFooter();
  });

  it("/login", async () => {
    render(<LoginPage />);
    await expectHeaderAndFooter();
  });

  it("/dashboard", async () => {
    render(<LearnerDashboard />);
    // Dashboard shows a loading state until /users/me/dashboard resolves.
    // Our fetch mock returns 401 for that route so the page falls into
    // its "Sign in" / error path — but the chrome should still wrap.
    await expectHeaderAndFooter();
  });

  it("/exams (listing)", async () => {
    render(<ExamSetsListPage />);
    await expectHeaderAndFooter();
  });

  it("/exams/results/:id", async () => {
    // Force the result fetch to 404 (no real attempt in tests). Page
    // falls into its error state — which we just made chrome-wrapped.
    const baseFetch = global.fetch;
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/exams/attempts/")) {
        return new Response(
          JSON.stringify({ error: { code: "not_found", message: "no attempt" } }),
          { status: 404, headers: { "Content-Type": "application/json" } },
        );
      }
      return baseFetch(input, init);
    }) as typeof fetch;

    render(<ResultsPage />);
    await expectHeaderAndFooter();
  });

  it("/pages/[slug] (CMS page)", async () => {
    // Return a published page from the public /cms/pages/{slug} endpoint
    // so the route renders content. Chrome must wrap so CMS pages look
    // and feel like the rest of the site.
    const baseFetch = global.fetch;
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/cms/pages/")) {
        return new Response(JSON.stringify({
          id: 1, slug: "demo", title: "Demo Page",
          blocks: [{ type: "paragraph", content: "Hello body" }],
          nav_visibility: "always", nav_label: null, nav_order: 100,
          is_landing: false, updated_at: "2026-05-19T00:00:00Z",
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return baseFetch(input, init);
    }) as typeof fetch;

    const ui = await PublicContentPage({ params: { slug: "demo" } });
    render(ui);
    await expectHeaderAndFooter();
  });

  it("/pricing", async () => {
    // Pricing page calls /pricing/plans on mount — return an empty list
    // so the page renders the empty-state body. Chrome should still wrap.
    const baseFetch = global.fetch;
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/pricing/plans")) {
        return new Response("[]", {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      return baseFetch(input, init);
    }) as typeof fetch;

    render(<PricingPage />);
    await expectHeaderAndFooter();
  });
});
