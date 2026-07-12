/**
 * 404 + error pages — render the admin-configurable copy and honor the
 * show_help_links toggle. The setup.tsx fetch mock returns "[]" for
 * unmatched routes, so both pages fall back to the seeded default copy
 * — exactly the API-down behavior we want pinned.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import NotFound from "@/app/not-found";
import RootError from "@/app/error";

describe("not-found page", () => {
  it("renders the default copy and help links when the API is unreachable", async () => {
    const jsx = await NotFound();          // async server component
    render(jsx);
    expect(screen.getByText("Uh oh! You seem to have lost your way.")).toBeInTheDocument();
    expect(screen.getByText("Let us help you find what you were looking for:")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mock exams" })).toHaveAttribute("href", "/exams");
    // "Pricing" also lives in the site header nav — the help block adds
    // a second one.
    const pricingLinks = screen.getAllByRole("link", { name: "Pricing" });
    expect(pricingLinks.length).toBeGreaterThanOrEqual(2);
  });

  it("hides the help links when the admin toggles them off", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = input.toString();
      if (url.includes("/content/errors")) {
        return new Response(JSON.stringify({
          not_found_title: "Custom lost title",
          not_found_body: "",
          show_help_links: false,
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response("[]", { status: 200,
        headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;

    const jsx = await NotFound();
    render(jsx);
    expect(screen.getByText("Custom lost title")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Mock exams" })).toBeNull();
  });

  it("shows the live-class registration link when banner + toggle are on", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = input.toString();
      if (url.includes("/content/errors")) {
        return new Response(JSON.stringify({
          not_found_title: "Lost?", not_found_body: "", show_help_links: true,
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/content/landing")) {
        return new Response(JSON.stringify({
          live_banner_enabled: true,
          live_banner_link_url: "https://zoom.us/register/x",
          live_banner_link_label: "Join live classes",
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response("[]", { status: 200,
        headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;

    const jsx = await NotFound();
    render(jsx);
    const reg = screen.getByRole("link", { name: /Join live classes/ });
    expect(reg).toHaveAttribute("href", "https://zoom.us/register/x");
    expect(reg).toHaveAttribute("target", "_blank");
  });
});

describe("error page", () => {
  it("renders fallback copy, a Try again button, and help links", async () => {
    render(<RootError error={new Error("boom")} reset={() => {}} />);
    expect(screen.getByText("Something went wrong on our end")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("link", { name: "Home" })).toBeInTheDocument();
    });
  });
});
