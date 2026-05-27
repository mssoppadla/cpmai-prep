/**
 * Tracker route-template derivation tests.
 *
 * The visitor-insights dashboard groups events by route template
 * ("/courses/[slug]") not raw URL ("/courses/cpmai-foundation-2026").
 * That grouping has to AUTO-SCALE as the team adds new dynamic
 * routes — no one will remember to update a server-side regex
 * registry every PR.
 *
 * Our solution is `deriveRouteTemplate(pathname, params)` which
 * uses the values Next.js already gives us via useParams() to
 * replace each dynamic segment in the URL with [paramName]. As
 * long as the new route is a regular Next.js dynamic route, the
 * tracker auto-rolls-up the day it's deployed.
 *
 * The drift-protection test at the bottom of this file walks every
 * dynamic-route directory under src/app and asserts the derivation
 * works for each, so a future PR adding a new dynamic route cannot
 * silently regress this property.
 */
import { describe, it, expect } from "vitest";
import { readdirSync, statSync } from "fs";
import { join } from "path";
import { deriveRouteTemplate } from "@/components/tracker/TrackerMount";


describe("deriveRouteTemplate", () => {
  it("returns the path unchanged when there are no params", () => {
    expect(deriveRouteTemplate("/about", {})).toBe("/about");
    expect(deriveRouteTemplate("/pricing", null)).toBe("/pricing");
    expect(deriveRouteTemplate("/", {})).toBe("/");
  });

  it("returns '/' for falsy pathname", () => {
    expect(deriveRouteTemplate("", { slug: "x" })).toBe("/");
  });

  it("replaces a single dynamic segment", () => {
    expect(
      deriveRouteTemplate("/courses/cpmai-foundation-2026", {
        slug: "cpmai-foundation-2026",
      }),
    ).toBe("/courses/[slug]");
  });

  it("replaces multiple dynamic segments at different positions", () => {
    expect(
      deriveRouteTemplate("/courses/foo/lessons/42", {
        slug: "foo",
        lid: "42",
      }),
    ).toBe("/courses/[slug]/lessons/[lid]");
  });

  it("handles catch-all params (array values)", () => {
    expect(
      deriveRouteTemplate("/docs/api/v1/users", {
        path: ["api", "v1", "users"],
      }),
    ).toBe("/docs/[path]/[path]/[path]");
  });

  it("preserves literal segments that don't match any param", () => {
    expect(
      deriveRouteTemplate("/admin/courses/42/edit", {
        id: "42",
      }),
    ).toBe("/admin/courses/[id]/edit");
  });

  it("doesn't replace a segment that happens to look like a slug but isn't in params", () => {
    // /about/leadership has "leadership" — looks slug-y but not a
    // dynamic param. Stays literal.
    expect(
      deriveRouteTemplate("/about/leadership", {}),
    ).toBe("/about/leadership");
  });

  it("handles trailing slash gracefully", () => {
    expect(
      deriveRouteTemplate("/courses/foo/", { slug: "foo" }),
    ).toBe("/courses/[slug]/");
  });
});


/**
 * Drift-protection test — walks every dynamic-route directory under
 * frontend/src/app/ and asserts deriveRouteTemplate would normalise
 * a representative URL for it.
 *
 * If someone adds a new ``app/instructors/[name]/page.tsx`` route,
 * this test will pick it up automatically. The fixture data is
 * generated from the directory structure, not a hardcoded list.
 *
 * If this test fails after adding a new route, the answer is usually
 * "good — your new route is now covered" because the fixture is
 * regenerated each run. A failure here typically means
 * deriveRouteTemplate has a bug that breaks the new shape.
 */
describe("dynamic-route coverage (drift protection)", () => {
  const APP_DIR = join(__dirname, "..", "app");

  function walkForDynamicRoutes(dir: string, prefix = ""): {
    routePath: string;
    paramName: string;
    paramKey: string;
  }[] {
    const out: { routePath: string; paramName: string; paramKey: string }[] = [];
    let entries: string[];
    try {
      entries = readdirSync(dir);
    } catch {
      return out;
    }
    for (const name of entries) {
      const full = join(dir, name);
      let stat;
      try { stat = statSync(full); } catch { continue; }
      if (!stat.isDirectory()) continue;

      // Skip Next.js route groups like (app), (auth) — they don't
      // contribute to the URL.
      const urlPart = name.startsWith("(") && name.endsWith(")")
        ? ""
        : "/" + name;
      const childPrefix = prefix + urlPart;

      // If this is a [param] directory, record it.
      const m = name.match(/^\[(?:\.{3})?(\w+)\]$/);
      if (m) {
        out.push({
          routePath: childPrefix,
          paramName: `[${m[1]}]`,
          paramKey: m[1],
        });
      }

      // Recurse — dynamic routes may nest (/courses/[slug]/lessons/[lid])
      out.push(...walkForDynamicRoutes(full, childPrefix));
    }
    return out;
  }

  const dynamicRoutes = walkForDynamicRoutes(APP_DIR);

  it("discovers at least one dynamic route (sanity)", () => {
    expect(dynamicRoutes.length).toBeGreaterThan(0);
  });

  it.each(dynamicRoutes)(
    "normalises $routePath correctly (auto-discovered)",
    ({ routePath, paramName, paramKey }) => {
      // Synthesize a realistic raw URL by replacing each [param]
      // with a slug-ish value, then run derivation with the same
      // params Next.js would surface.
      const sampleValue = `sample-${paramKey}-value-2026`;

      // Build a params object covering every dynamic segment in this
      // route. e.g. for /courses/[slug]/lessons/[lid] we walk the
      // path and gather {slug:"sample-slug-...", lid:"sample-lid-..."}.
      const params: Record<string, string> = {};
      const segments = routePath.split("/");
      const rawSegments = segments.map((seg) => {
        const sm = seg.match(/^\[(?:\.{3})?(\w+)\]$/);
        if (sm) {
          const v = `sample-${sm[1]}-2026`;
          params[sm[1]] = v;
          return v;
        }
        return seg;
      });
      const rawPath = rawSegments.join("/");

      const template = deriveRouteTemplate(rawPath, params);

      // The derived template MUST include the dynamic placeholder for
      // this particular param. If a new route's params aren't being
      // collapsed, this fails — surfacing the regression at CI time.
      expect(template).toContain(paramName);
      // Sanity: no raw "sample-" value should leak through for the
      // tested param.
      expect(template).not.toContain(params[paramKey]);
    },
  );
});
