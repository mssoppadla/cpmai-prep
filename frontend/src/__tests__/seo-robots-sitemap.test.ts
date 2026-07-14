/**
 * robots.ts + sitemap.ts — the indexability contract.
 *
 * Pins: private routes stay disallowed, the sitemap lists static
 * marketing pages plus every published course and public CMS page,
 * and NO private route ever leaks into the sitemap.
 */
import { describe, expect, it, vi } from "vitest";
import robots from "@/app/robots";
import sitemap from "@/app/sitemap";

describe("robots.txt", () => {
  it("allows public crawl and disallows admin/user/transactional routes", () => {
    const r = robots();
    const rule = Array.isArray(r.rules) ? r.rules[0] : r.rules;
    expect(rule.allow).toBe("/");
    for (const path of ["/admin", "/dashboard", "/sessions",
                         "/payments", "/exams/results", "/api"]) {
      expect(rule.disallow).toContain(path);
    }
    expect(String(r.sitemap)).toMatch(/\/sitemap\.xml$/);
  });
});

describe("sitemap.xml", () => {
  it("lists statics + published courses + public CMS pages", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = input.toString();
      if (url.includes("/lms/courses")) {
        return new Response(JSON.stringify([
          { slug: "cpmai-fundamentals", updated_at: "2026-07-01T00:00:00Z" },
          { slug: "advanced-mlops" },
        ]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/cms/nav")) {
        return new Response(JSON.stringify([
          { slug: "study-guide" },
        ]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response("[]", { status: 200,
        headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;

    const entries = await sitemap();
    const urls = entries.map((e) => e.url);
    for (const must of ["/", "/pricing", "/courses", "/exams",
                         "/courses/cpmai-fundamentals",
                         "/courses/advanced-mlops",
                         "/pages/study-guide"]) {
      expect(urls.some((u) => u.endsWith(must))).toBe(true);
    }
    // Never leak private surfaces.
    expect(urls.some((u) => /admin|dashboard|sessions|payments/.test(u)))
      .toBe(false);
  });

  it("degrades to statics when the API is down", async () => {
    global.fetch = vi.fn(async () => { throw new Error("down"); }) as typeof fetch;
    const entries = await sitemap();
    expect(entries.length).toBeGreaterThanOrEqual(6);
    expect(entries[0].url.endsWith("/")).toBe(true);
  });
});
