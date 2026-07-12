/** Crop math for the testimonial photo cropper — pure functions. */
import { describe, expect, it } from "vitest";
import {
  centeredOffset, clampOffset, layoutFor, offsetAfterZoom, sourceRect,
} from "@/lib/crop";

// A 4000×3000 photo in a 800×450 (16:9) viewport.
const NW = 4000, NH = 3000, CW = 800, CH = 450;

describe("layoutFor", () => {
  it("covers the viewport at zoom 1 (no blank space on either axis)", () => {
    const { displayW, displayH } = layoutFor(NW, NH, CW, CH, 1);
    expect(displayW).toBeGreaterThanOrEqual(CW);
    expect(displayH).toBeGreaterThanOrEqual(CH);
    // Landscape-ish photo taller than 16:9 → width fits exactly.
    expect(displayW).toBeCloseTo(CW);
    expect(displayH).toBeCloseTo(600);   // 3000 × (800/4000)
  });

  it("scales linearly with zoom", () => {
    const z1 = layoutFor(NW, NH, CW, CH, 1);
    const z2 = layoutFor(NW, NH, CW, CH, 2);
    expect(z2.displayW).toBeCloseTo(z1.displayW * 2);
    expect(z2.displayH).toBeCloseTo(z1.displayH * 2);
  });
});

describe("clampOffset", () => {
  it("never lets the image edge enter the viewport", () => {
    const { displayW, displayH } = layoutFor(NW, NH, CW, CH, 1);
    // Try to drag way past every edge.
    expect(clampOffset(500, 500, displayW, displayH, CW, CH))
      .toEqual({ ox: 0, oy: 0 });
    const farOut = clampOffset(-99999, -99999, displayW, displayH, CW, CH);
    expect(farOut.ox).toBeCloseTo(CW - displayW);
    expect(farOut.oy).toBeCloseTo(CH - displayH);
  });
});

describe("sourceRect", () => {
  it("centered at zoom 1 exposes the middle strip of the photo", () => {
    const { displayW, displayH } = layoutFor(NW, NH, CW, CH, 1);
    const { ox, oy } = centeredOffset(displayW, displayH, CW, CH);
    const r = sourceRect(ox, oy, NW, NH, CW, CH, 1);
    expect(r.sx).toBeCloseTo(0);          // full width used
    expect(r.sw).toBeCloseTo(NW);
    expect(r.sy).toBeCloseTo((NH - r.sh) / 2);  // vertically centered
    expect(r.sw / r.sh).toBeCloseTo(CW / CH);   // aspect preserved
  });

  it("zooming in shrinks the source region around what's visible", () => {
    const { displayW, displayH } = layoutFor(NW, NH, CW, CH, 2);
    const { ox, oy } = centeredOffset(displayW, displayH, CW, CH);
    const r = sourceRect(ox, oy, NW, NH, CW, CH, 2);
    expect(r.sw).toBeCloseTo(NW / 2);
    expect(r.sw / r.sh).toBeCloseTo(CW / CH);
    // Region stays inside the photo.
    expect(r.sx).toBeGreaterThanOrEqual(0);
    expect(r.sx + r.sw).toBeLessThanOrEqual(NW + 0.001);
  });
});

describe("offsetAfterZoom", () => {
  it("keeps the viewport-center pixel fixed while zooming", () => {
    const l1 = layoutFor(NW, NH, CW, CH, 1.5);
    const start = clampOffset(-120, -80, l1.displayW, l1.displayH, CW, CH);
    const before = sourceRect(start.ox, start.oy, NW, NH, CW, CH, 1.5);
    const centerBefore = { x: before.sx + before.sw / 2, y: before.sy + before.sh / 2 };

    const next = offsetAfterZoom(start.ox, start.oy, NW, NH, CW, CH, 1.5, 2.5);
    const after = sourceRect(next.ox, next.oy, NW, NH, CW, CH, 2.5);
    const centerAfter = { x: after.sx + after.sw / 2, y: after.sy + after.sh / 2 };

    expect(centerAfter.x).toBeCloseTo(centerBefore.x, 5);
    expect(centerAfter.y).toBeCloseTo(centerBefore.y, 5);
  });

  it("re-clamps when zooming out would reveal blank space", () => {
    // Fully dragged to the bottom-right at 3×, then zoom out to 1×.
    const l3 = layoutFor(NW, NH, CW, CH, 3);
    const dragged = clampOffset(-99999, -99999, l3.displayW, l3.displayH, CW, CH);
    const next = offsetAfterZoom(dragged.ox, dragged.oy, NW, NH, CW, CH, 3, 1);
    const l1 = layoutFor(NW, NH, CW, CH, 1);
    expect(next.ox).toBeGreaterThanOrEqual(CW - l1.displayW - 0.001);
    expect(next.ox).toBeLessThanOrEqual(0.001);
    expect(next.oy).toBeGreaterThanOrEqual(CH - l1.displayH - 0.001);
    expect(next.oy).toBeLessThanOrEqual(0.001);
  });
});
