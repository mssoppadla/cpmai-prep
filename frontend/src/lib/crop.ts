/**
 * Pure math for the admin image cropper (testimonial photos).
 *
 * Model: an image of natural size (NW×NH) is displayed inside a fixed
 * crop viewport (CW×CH) at scale = coverScale × zoom, translated so its
 * top-left sits at (ox, oy) relative to the viewport's top-left. The
 * visible viewport region is what gets exported.
 *
 * All functions are side-effect-free so they can be unit-tested without
 * a DOM.
 */

export interface CropLayout {
  /** Scale that makes the image exactly cover the viewport at zoom 1. */
  coverScale: number;
  /** Displayed image size at the given zoom. */
  displayW: number;
  displayH: number;
}

export function layoutFor(
  naturalW: number, naturalH: number,
  viewportW: number, viewportH: number,
  zoom: number,
): CropLayout {
  const coverScale = Math.max(viewportW / naturalW, viewportH / naturalH);
  const s = coverScale * zoom;
  return { coverScale, displayW: naturalW * s, displayH: naturalH * s };
}

/** Clamp the image offset so the viewport never shows blank space:
 *  ox ∈ [CW − DW, 0], oy ∈ [CH − DH, 0]. */
export function clampOffset(
  ox: number, oy: number,
  displayW: number, displayH: number,
  viewportW: number, viewportH: number,
): { ox: number; oy: number } {
  return {
    ox: Math.min(0, Math.max(viewportW - displayW, ox)),
    oy: Math.min(0, Math.max(viewportH - displayH, oy)),
  };
}

/** Offset that centers the image in the viewport (initial state). */
export function centeredOffset(
  displayW: number, displayH: number,
  viewportW: number, viewportH: number,
): { ox: number; oy: number } {
  return { ox: (viewportW - displayW) / 2, oy: (viewportH - displayH) / 2 };
}

/** The source rectangle (in natural-image pixels) currently visible in
 *  the viewport — i.e. what canvas.drawImage should copy out. */
export function sourceRect(
  ox: number, oy: number,
  naturalW: number, naturalH: number,
  viewportW: number, viewportH: number,
  zoom: number,
): { sx: number; sy: number; sw: number; sh: number } {
  const s = layoutFor(naturalW, naturalH, viewportW, viewportH, zoom).coverScale * zoom;
  return { sx: -ox / s, sy: -oy / s, sw: viewportW / s, sh: viewportH / s };
}

/** Re-clamp the offset after a zoom change, keeping the viewport
 *  CENTER pointing at the same image pixel (zoom toward the middle). */
export function offsetAfterZoom(
  ox: number, oy: number,
  naturalW: number, naturalH: number,
  viewportW: number, viewportH: number,
  oldZoom: number, newZoom: number,
): { ox: number; oy: number } {
  const coverScale = layoutFor(naturalW, naturalH, viewportW, viewportH, 1).coverScale;
  const ratio = (coverScale * newZoom) / (coverScale * oldZoom);
  // Image pixel under the viewport center stays fixed:
  //   center = -ox + CW/2 (in display px) → scales by ratio.
  const cx = -ox + viewportW / 2;
  const cy = -oy + viewportH / 2;
  const next = { ox: -(cx * ratio) + viewportW / 2, oy: -(cy * ratio) + viewportH / 2 };
  const { displayW, displayH } = layoutFor(naturalW, naturalH, viewportW, viewportH, newZoom);
  return clampOffset(next.ox, next.oy, displayW, displayH, viewportW, viewportH);
}
