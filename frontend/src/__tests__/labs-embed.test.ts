/**
 * Lab embed truncation — the server-side cut that keeps locked
 * sections out of the browser, and the lock copy per access reason.
 */
import { describe, it, expect } from "vitest";
import {
  buildLockUi, labEmbedUrl, lockCopy, parseMarkers, truncateLabHtml,
} from "@/lib/labs";
import type { LabAccessOut } from "@/types/api";

const SECS = [
  { id: "sec1", title: "1 · Data ready" },
  { id: "sec2", title: "2 · Training" },
  { id: "legend", title: "Legend" },
  { id: "abbr", title: "Abbreviations" },
];

const ASSET = `<!doctype html><html><head><title>t</title></head><body>
<header>intro</header>
<figure><svg viewBox="0 0 1600 1000">
<!--LABSEC id="sec1" y="20" close="</svg></figure>"-->
<text>SECTION ONE SECRET-1</text>
<!--LABSEC id="sec2" y="500" close="</svg></figure>"-->
<text>SECTION TWO SECRET-2</text>
</svg></figure>
<!--LABSEC id="legend"-->
<div class="legend">LEGEND SECRET-3</div>
<!--LABSEC id="abbr"-->
<section class="abbr">ABBR SECRET-4</section>
<!--LABSEC:END-->
<script>/*trailing*/</script>
</body></html>`;

function access(over: Partial<LabAccessOut>): LabAccessOut {
  const upto = over.free_upto_index ?? -1;
  return {
    slug: "ml-training-pipeline", title: "ML", enabled: true, mode: "preview",
    full: false, reason: "plan", free_upto_index: upto, sections: SECS,
    locked_sections: SECS.slice(upto + 1), plans: [], embed_token: "tok",
    ...over,
  };
}

describe("parseMarkers", () => {
  it("finds every section marker in order with y/close where present", () => {
    const { markers, end } = parseMarkers(ASSET);
    expect(markers.map(m => m.id)).toEqual(["sec1", "sec2", "legend", "abbr"]);
    expect(markers[1].y).toBe(500);
    expect(markers[1].close).toBe("</svg></figure>");
    expect(markers[2].y).toBeNull();
    expect(end).toBeGreaterThan(0);
  });
});

describe("truncateLabHtml", () => {
  it("returns the asset untouched for full access", () => {
    expect(truncateLabHtml(ASSET, access({ full: true, reason: "ok" }), "/labs/x")).toBe(ASSET);
  });

  it("cuts inside the svg: keeps free sections, closes the svg, shrinks the viewBox, drops the rest", () => {
    const out = truncateLabHtml(ASSET, access({ free_upto_index: 0 }), "/labs/x");
    expect(out).toContain("SECRET-1");
    expect(out).not.toContain("SECRET-2");
    expect(out).not.toContain("SECRET-3");
    expect(out).not.toContain("SECRET-4");
    expect(out).toContain('viewBox="0 0 1600 500"');
    expect(out).toContain("</svg></figure>");
    expect(out).toContain("lab-lock");
    expect(out).toContain("/*trailing*/");       // scripts after END survive
    expect(out).not.toContain("<!--LABSEC");      // no marker leaks
    expect(out).toContain("3 more sections");
  });

  it("cuts at an html section: svg stays whole, only later html sections go", () => {
    const out = truncateLabHtml(ASSET, access({ free_upto_index: 2 }), "/labs/x");
    expect(out).toContain("SECRET-1");
    expect(out).toContain("SECRET-2");
    expect(out).toContain("SECRET-3");
    expect(out).not.toContain("SECRET-4");
    expect(out).toContain('viewBox="0 0 1600 1000"');
    expect(out).toContain("1 more section:");
  });

  it("nothing free → header only plus the lock", () => {
    const out = truncateLabHtml(ASSET, access({ free_upto_index: -1 }), "/labs/x");
    expect(out).toContain("intro");
    expect(out).not.toMatch(/SECRET-[1-4]/);
    expect(out).toContain("This lab is part of a plan");
  });

  it("an asset without markers is all-or-nothing", () => {
    const out = truncateLabHtml("<html><body>WHOLE APP</body></html>",
      access({ mode: "plan", free_upto_index: -1, locked_sections: [] }), "/labs/x");
    expect(out).not.toContain("WHOLE APP");
    expect(out).toContain("lab-lock");
  });

  it("escapes plan names and section titles in the lock panel", () => {
    const out = buildLockUi(access({
      plans: [{ slug: "p", name: "<b>Plan</b>" }],
      locked_sections: [{ id: "x", title: "<img src=x>" }],
    }), "/labs/x");
    expect(out).not.toContain("<b>Plan</b>");
    expect(out).toContain("&lt;b&gt;Plan&lt;/b&gt;");
    expect(out).not.toContain("<img src=x>");
  });
});

describe("lockCopy", () => {
  it("sign-in mode asks for an account, never for a plan", () => {
    const c = lockCopy(access({ mode: "signin", reason: "signin", locked_sections: SECS }), "/labs/ml");
    expect(c.title).toMatch(/Sign in/);
    expect(c.primaryHref).toBe("/login?next=%2Flabs%2Fml");
    expect(c.plans).toBe("");
  });
  it("plan mode names the plans that unlock the lab", () => {
    const c = lockCopy(access({ plans: [{ slug: "a", name: "Course plan" }] }), "/labs/ml");
    expect(c.plans).toContain("Course plan");
    expect(c.primaryHref).toBe("/pricing");
    expect(c.secondaryHref).toBe("/login?next=%2Flabs%2Fml");
  });
});

describe("labEmbedUrl", () => {
  it("carries the version and the token", () => {
    expect(labEmbedUrl("x", "abc")).toBe("/labs/embed/x?v=1&t=abc");
    expect(labEmbedUrl("x")).toBe("/labs/embed/x?v=1");
  });
});
