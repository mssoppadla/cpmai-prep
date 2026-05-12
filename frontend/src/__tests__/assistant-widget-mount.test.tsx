/**
 * Regression gate: the AssistantWidget bubble MUST appear for every
 * signed-in user, on every page, and MUST stay hidden for anonymous
 * visitors.
 *
 * Built after a May-2026 prod incident where a refresh showed no chat
 * icon — likely because the user got logged out, but a real code
 * regression would have looked identical. This test pins down the
 * contract so any future change that breaks either condition fails
 * CI before merge:
 *
 *   1. ``AssistantWidgetMount`` calls ``auth.me()`` on mount and only
 *      renders ``AssistantWidget`` after the probe completes. (Defers
 *      the bubble flash on anon page loads.)
 *
 *   2. When ``auth.me()`` resolves to a User, ``AssistantWidget``
 *      renders the floating bubble button (aria-label = "Open AI
 *      assistant"). This is the user-visible contract.
 *
 *   3. When ``auth.me()`` 401s, the widget renders NOTHING — no
 *      bubble, no panel. Marketing pages stay clean.
 *
 * The mount lives in ``app/layout.tsx`` (root), so every page in the
 * Next.js app inherits it. We don't test that the mount is in the
 * layout (TypeScript / build would catch a missing import) — we test
 * the behavior the user actually sees once it's mounted.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantWidgetMount } from "@/components/assistant/AssistantWidgetMount";


function stubAuth(meResponse: { status: number; body: unknown }) {
  // Override the default fetch stub from setup.tsx so /users/me returns
  // what this test wants. Everything else falls back to setup.tsx's
  // empty-200 default. ``vi.fn`` so tests stay isolated.
  const baseFetch = global.fetch;
  global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/users/me")) {
      return new Response(JSON.stringify(meResponse.body), {
        status: meResponse.status,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/content/site")) {
      return new Response(JSON.stringify({
        brand_name: "CPMAI Prep", tagline: "", support_email: "",
        linkedin_url: "", youtube_url: "", twitter_url: "",
        copyright_text: "", show_pricing_link: true,
        assistant_widget_subtitle: "",
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    // Notifications / leads / assistant.chat — all should return empty
    // success so the widget mounts without surfacing errors.
    return new Response("[]", {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
  return baseFetch;
}


describe("AssistantWidgetMount — chat bubble visibility contract", () => {
  beforeEach(() => {
    // Token presence isn't what the widget checks — it depends on
    // ``auth.me()`` succeeding. Both states are exercised by the tests.
    window.localStorage.clear();
  });

  it("renders the floating bubble when /users/me returns a real user",
     async () => {
    window.localStorage.setItem("cpmai.access", "fake.jwt.token");
    stubAuth({
      status: 200,
      body: { id: 1, email: "test@example.com", name: "Test User",
              role: "user", created_at: "2026-01-01T00:00:00Z" },
    });

    render(<AssistantWidgetMount />);

    // The mount defers rendering until auth.me() resolves, so we wait.
    // Aria-label is the user-visible contract — screen readers AND
    // keyboard users navigate to the widget through it.
    const bubble = await waitFor(() => screen.getByRole("button", {
      name: /open ai assistant/i,
    }));
    expect(bubble).toBeInTheDocument();
  });

  it("renders NOTHING when /users/me returns 401 (anonymous visitor)",
     async () => {
    stubAuth({
      status: 401,
      body: { error: { code: "unauthorized", message: "" } },
    });

    const { container } = render(<AssistantWidgetMount />);

    // Wait for the probe to complete (cleanup runs after each test, so
    // the probe always fires). The result MUST be an empty container —
    // no bubble, no panel, no flash of unauthed UI.
    await waitFor(() => {
      // After probe, "probed" goes true; if user is null, AssistantWidget
      // returns null too. So container should still be empty.
      expect(container.querySelector("button")).toBeNull();
    });

    // Belt + suspenders: the aria-label must NOT appear anywhere.
    expect(screen.queryByRole("button", {
      name: /open ai assistant/i,
    })).toBeNull();
  });

  it("renders NOTHING during the pre-probe window (no bubble flash)",
     () => {
    // auth.me() returns a never-resolving promise so we can observe the
    // pre-probe state. AssistantWidgetMount guards with ``if (!probed)
    // return null`` precisely to prevent the bubble flashing in and out
    // on anon page loads where the probe later 401s.
    global.fetch = vi.fn(() => new Promise(() => { /* never */ })) as typeof fetch;

    const { container } = render(<AssistantWidgetMount />);

    expect(container.firstChild).toBeNull();
  });
});
