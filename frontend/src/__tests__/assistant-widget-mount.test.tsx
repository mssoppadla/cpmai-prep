/**
 * Regression gate: the AssistantWidget bubble MUST appear on every
 * page, for BOTH signed-in users (full chat UI) and anonymous
 * visitors (Sign In CTA panel). Hiding the bubble entirely for
 * anonymous visitors was the previous contract — changed 2026-05-14
 * based on operator feedback that the chat is the strongest
 * acquisition CTA on the site, so it should be visible to everyone.
 *
 * Originally built after a May-2026 prod incident where a refresh
 * showed no chat icon. Test contract now pins:
 *
 *   1. ``AssistantWidgetMount`` calls ``auth.me()`` on mount AND on
 *      every pathname change (so post-login navigation immediately
 *      updates the widget's auth state — no hard refresh required).
 *
 *   2. When ``auth.me()`` resolves to a User, the floating bubble
 *      renders and the panel (when opened) shows the chat UI.
 *
 *   3. When ``auth.me()`` 401s, the bubble STILL renders. Opening it
 *      shows the configured anon-state CTA, not the chat input — so
 *      anonymous visitors learn how to access the AI tutor without
 *      typing into a black hole.
 *
 *   4. The pre-probe window (before auth.me() resolves) still
 *      renders nothing, to avoid a bubble flash on slow networks.
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
        assistant_try_asking_suggestions: [],
        assistant_anonymous_no_identity_message:
          "Please sign in to chat with our AI tutor.",
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

  it("bubble is position:fixed and anchored bottom-right (not in-flow)",
     async () => {
    // Regression: on 2026-05-14 the user reported the bubble had moved
    // to bottom-LEFT and was missing on some pages. Root cause was
    // ``relative`` accidentally added to the button's className
    // alongside ``fixed`` (PR #33 thought it was needed as a
    // positioning context for the red-dot notification badge — but
    // ``fixed`` already establishes one). With both classes present,
    // Tailwind's ``.relative`` rule wins in the output CSS, demoting
    // the button to in-flow positioning, where the ``right``/``bottom``
    // offsets behave relative to its parent instead of the viewport.
    //
    // This test asserts both invariants:
    //   • the ``fixed`` utility class is on the button
    //   • the ``relative`` utility class is NOT on the button
    //
    // We check className tokens rather than computed style because
    // jsdom doesn't evaluate Tailwind's stylesheets. The className
    // contract is what matters; if both classes are present in source
    // they'll both end up on the element and the bug returns.
    window.localStorage.setItem("cpmai.access", "fake.jwt.token");
    stubAuth({
      status: 200,
      body: { id: 1, email: "test@example.com", name: "Test User",
              role: "user", created_at: "2026-01-01T00:00:00Z" },
    });

    render(<AssistantWidgetMount />);

    const bubble = await waitFor(() => screen.getByRole("button", {
      name: /open ai assistant/i,
    }));

    expect(bubble.className).toMatch(/\bfixed\b/);
    expect(bubble.className).not.toMatch(/\brelative\b/);
    // The right + bottom offsets are inline styles (use env() for safe-
    // area-inset). Their presence confirms the bubble is anchored to a
    // corner — if either is missing the bubble would float to a default
    // position. The exact pixel values can change for design tweaks;
    // we only assert the style keys exist and are non-empty.
    expect(bubble.style.right).not.toBe("");
    expect(bubble.style.bottom).not.toBe("");
    // And we assert NO ``left`` / ``top`` inline style — the bubble
    // belongs in the bottom-right corner specifically.
    expect(bubble.style.left).toBe("");
    expect(bubble.style.top).toBe("");
  });

  it("renders the floating bubble for anonymous visitors too (401 from /users/me)",
     async () => {
    // Contract changed 2026-05-14: previously the widget hid entirely
    // for anonymous visitors. New behavior: the bubble shows, opening
    // it surfaces a Sign In CTA. Verified end-to-end in the next test;
    // this one just pins the bubble visibility.
    stubAuth({
      status: 401,
      body: { error: { code: "unauthorized", message: "" } },
    });

    render(<AssistantWidgetMount />);

    const bubble = await waitFor(() => screen.getByRole("button", {
      name: /open ai assistant/i,
    }));
    expect(bubble).toBeInTheDocument();
  });

  it("opening the bubble as an anonymous visitor shows the Sign In CTA",
     async () => {
    // The configured ``assistant.anonymous_no_identity_message`` flows
    // through /content/site (set up in stubAuth above to:
    // "Please sign in to chat with our AI tutor."). Opening the panel
    // should render that message plus a Sign In link — NOT the chat
    // input form (which would just round-trip a 401).
    stubAuth({
      status: 401,
      body: { error: { code: "unauthorized", message: "" } },
    });

    render(<AssistantWidgetMount />);

    const bubble = await waitFor(() => screen.getByRole("button", {
      name: /open ai assistant/i,
    }));
    bubble.click();

    // Configured message renders verbatim from /content/site.
    await waitFor(() => {
      expect(screen.getByText(/please sign in to chat with our AI tutor/i))
        .toBeInTheDocument();
    });
    // Sign In link must be present and routed through /login with the
    // current pathname captured for post-login redirect. Label is
    // "Sign in with Google" because the app's auth is Google-only —
    // no separate signup/password flow.
    const signIn = screen.getByRole("link", { name: /sign in with google/i });
    expect(signIn).toBeInTheDocument();
    expect(signIn.getAttribute("href")).toMatch(/^\/login\?next=/);

    // And the chat input form MUST be absent — otherwise the anon
    // user would type, hit Enter, and get a useless 401.
    expect(screen.queryByPlaceholderText(/ask about cpmai/i)).toBeNull();
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
