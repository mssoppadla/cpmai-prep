/**
 * Rich-text explanations (2026-09): "General explanation" and per-option
 * "Why this is wrong" accept formatting/emoji/images — while EXISTING
 * plain-text rows must render exactly as before. These pins guard the
 * backward-compatibility contract (no migration, format detected per
 * value) and the sanitizer's new img allowance.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { looksLikeHtml, RichTextView } from "@/components/RichText";
import { sanitizeHtml } from "@/lib/sanitizeHtml";

describe("looksLikeHtml — legacy data must stay plain", () => {
  it("treats existing plain explanations as plain, even with < > or emoji", () => {
    expect(looksLikeHtml("Phase 2 comes before Phase 3.")).toBe(false);
    expect(looksLikeHtml("score < 70% means fail 🎯")).toBe(false);
    expect(looksLikeHtml("a <threshold> is not a tag")).toBe(false);
    expect(looksLikeHtml("line one\nline two")).toBe(false);
  });
  it("detects editor-authored markup", () => {
    expect(looksLikeHtml("<p>Because <b>CRISP-DM</b> differs</p>")).toBe(true);
    expect(looksLikeHtml('an image <img src="/uploads/1/a.png">')).toBe(true);
    expect(looksLikeHtml("first<br>second")).toBe(true);
  });
});

describe("RichTextView", () => {
  it("renders legacy plain text verbatim (no HTML interpretation)", () => {
    render(<RichTextView value={"Wrong because A < B & emoji 🎯"} />);
    expect(screen.getByText(/Wrong because A < B & emoji 🎯/)).toBeTruthy();
  });
  it("renders editor HTML with images through the sanitizer", () => {
    const { container } = render(
      <RichTextView value={'<p>See:</p><img src="/uploads/1/x.png" alt="chart"><script>alert(1)</script>'} />,
    );
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("/uploads/1/x.png");
    expect(container.querySelector("script")).toBeNull();
  });
});

describe("sanitizeHtml img rules", () => {
  it("keeps http(s) and /uploads/ sources, adds lazy loading", () => {
    expect(sanitizeHtml('<img src="/uploads/1/a.png">'))
      .toContain('src="/uploads/1/a.png" loading="lazy"');
    expect(sanitizeHtml('<img src="https://cpmaiexamprep.com/x.png">'))
      .toContain('loading="lazy"');
  });
  it("drops an img with an unsafe src entirely", () => {
    expect(sanitizeHtml('<img src="javascript:alert(1)">')).not.toContain("<img");
    expect(sanitizeHtml('<img onerror="x" src="data:image/png;base64,AA">'))
      .not.toContain("<img");
  });
});
