/**
 * Global test setup — runs once before any test file.
 *
 * - @testing-library/jest-dom adds matchers like toBeInTheDocument
 * - Stub browser APIs that jsdom doesn't fully implement (matchMedia,
 *   IntersectionObserver) so components that touch them don't blow up
 *   on import.
 * - Reset fetch mock + localStorage between tests for isolation.
 */
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// matchMedia — used by Tailwind's @media queries via window.matchMedia
// and some libraries. jsdom doesn't ship it.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}

// next/navigation hooks — replace with controllable stubs so components
// using useRouter / useSearchParams / useParams don't crash in tests.
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

// next/link is a thin wrapper around <a> — render plain anchors so
// jsdom's click handling stays predictable.
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...rest
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const anchorProps = rest as any;
    return (
      <a href={href} {...anchorProps}>
        {children}
      </a>
    );
  },
}));

beforeEach(() => {
  // Each test gets a fresh fetch stub. Override per-test with vi.mocked(fetch)
  // .mockResolvedValueOnce(...). Default returns the fallback site-chrome
  // payload so SiteHeader/SiteFooter don't 404 their network call.
  const defaultSitePayload = {
    brand_name: "CPMAI Prep",
    tagline: "Pass the CPMAI certification on your first attempt.",
    support_email: "",
    linkedin_url: "",
    youtube_url: "",
    twitter_url: "",
    copyright_text: "© 2026 CPMAI Prep. All rights reserved.",
    show_pricing_link: true,
    assistant_widget_subtitle: "Grounded in our FAQ, pricing & question explanations",
  };
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/content/site")) {
      return new Response(JSON.stringify(defaultSitePayload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.endsWith("/users/me") || url.endsWith("/users/me/dashboard")) {
      return new Response(JSON.stringify({ error: { code: "unauthorized", message: "" } }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }
    // Default: return an empty 200 so unrelated calls don't throw.
    return new Response("[]", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  if (typeof window !== "undefined") {
    window.localStorage.clear();
  }
});
