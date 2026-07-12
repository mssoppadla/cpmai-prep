"use client";
/**
 * Photo upload with a crop step — used by the testimonials admin.
 *
 * Flow: pick a file → a crop dialog opens with the image shown inside
 * a fixed 16:9 viewport → drag to reposition, slider (or mouse wheel /
 * pinch-drag) to zoom → "Use this crop" renders EXACTLY the visible
 * region to a canvas (1280×720 JPEG) and uploads that via the shared
 * /admin/uploads endpoint. The public card renders at the same 16:9
 * aspect, so what the admin frames here is what visitors see — no more
 * automatic center-crop cutting off faces.
 *
 * Hand-rolled (pointer events + canvas) to stay dependency-free, same
 * as the landing carousel. Math lives in @/lib/crop for unit testing.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import {
  centeredOffset, clampOffset, layoutFor, offsetAfterZoom, sourceRect,
} from "@/lib/crop";

const ASPECT = 16 / 9;
const EXPORT_W = 1280;
const EXPORT_H = 720;
const MAX_ZOOM = 4;

export function ImageCropUpload({ onUploaded, buttonLabel = "Click to choose a photo (JPG/PNG/WebP)" }: {
  onUploaded: (url: string) => void;
  buttonLabel?: string;
}) {
  const [src, setSrc] = useState<string | null>(null);       // object URL being cropped
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ ox: 0, oy: 0 });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  // Revoke the object URL when the dialog closes / component unmounts.
  useEffect(() => () => { if (src) URL.revokeObjectURL(src); }, [src]);

  function onPick(file: File) {
    setErr(null);
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      setImg(image); setSrc(url); setZoom(1);
      // Center once the viewport has rendered (next tick).
      requestAnimationFrame(() => {
        const vp = viewportRef.current?.getBoundingClientRect();
        if (!vp) return;
        const { displayW, displayH } = layoutFor(
          image.naturalWidth, image.naturalHeight, vp.width, vp.height, 1);
        setOffset(centeredOffset(displayW, displayH, vp.width, vp.height));
      });
    };
    image.onerror = () => { setErr("Could not read that image file."); URL.revokeObjectURL(url); };
    image.src = url;
  }

  const applyZoom = useCallback((next: number) => {
    const vp = viewportRef.current?.getBoundingClientRect();
    if (!vp || !img) return;
    const clamped = Math.min(MAX_ZOOM, Math.max(1, next));
    setOffset(o => offsetAfterZoom(
      o.ox, o.oy, img.naturalWidth, img.naturalHeight,
      vp.width, vp.height, zoom, clamped));
    setZoom(clamped);
  }, [img, zoom]);

  function onPointerDown(e: React.PointerEvent) {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY, ox: offset.ox, oy: offset.oy };
  }
  function onPointerMove(e: React.PointerEvent) {
    const d = dragRef.current;
    const vp = viewportRef.current?.getBoundingClientRect();
    if (!d || !vp || !img) return;
    const { displayW, displayH } = layoutFor(
      img.naturalWidth, img.naturalHeight, vp.width, vp.height, zoom);
    setOffset(clampOffset(
      d.ox + (e.clientX - d.x), d.oy + (e.clientY - d.y),
      displayW, displayH, vp.width, vp.height));
  }
  function endDrag() { dragRef.current = null; }

  async function confirmCrop() {
    const vp = viewportRef.current?.getBoundingClientRect();
    if (!vp || !img) return;
    setBusy(true); setErr(null);
    try {
      const { sx, sy, sw, sh } = sourceRect(
        offset.ox, offset.oy, img.naturalWidth, img.naturalHeight,
        vp.width, vp.height, zoom);
      const canvas = document.createElement("canvas");
      canvas.width = EXPORT_W; canvas.height = EXPORT_H;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Canvas unavailable in this browser.");
      ctx.drawImage(img, sx, sy, sw, sh, 0, 0, EXPORT_W, EXPORT_H);
      const blob: Blob = await new Promise((res, rej) =>
        canvas.toBlob(b => (b ? res(b) : rej(new Error("Crop failed."))),
                      "image/jpeg", 0.9));
      const file = new File([blob], "testimonial-photo.jpg", { type: "image/jpeg" });
      const uploaded = await admin.uploads.file(file);
      cancel();
      onUploaded(uploaded.url);
    } catch (e) {
      console.error("[image-crop] upload", e);
      setErr(errMsg(e));
    } finally { setBusy(false); }
  }

  function cancel() {
    if (src) URL.revokeObjectURL(src);
    setSrc(null); setImg(null); setZoom(1); setOffset({ ox: 0, oy: 0 });
  }

  const scale = (img && viewportRef.current)
    ? layoutFor(img.naturalWidth, img.naturalHeight,
                viewportRef.current.getBoundingClientRect().width,
                viewportRef.current.getBoundingClientRect().height, zoom)
    : null;

  return (
    <div>
      {err && <div role="alert" className="text-xs text-rose-600 mb-2">{err}</div>}

      {!src && (
        <label className="block border-2 border-dashed border-slate-300 rounded-lg p-4
                          text-center cursor-pointer text-sm text-slate-500
                          hover:border-indigo-400 hover:text-indigo-600 transition">
          <input type="file" accept="image/*" className="hidden"
                 onChange={(e) => {
                   const f = e.target.files?.[0];
                   if (f) onPick(f);
                   e.target.value = "";
                 }} />
          {buttonLabel}
        </label>
      )}

      {src && (
        <div className="border border-indigo-200 rounded-xl p-3 bg-slate-50 space-y-3">
          <div className="text-xs text-slate-600">
            Drag the photo to reposition · zoom to frame the part you want.
            The highlighted area is exactly what visitors will see on the card.
          </div>
          <div ref={viewportRef}
               role="application" aria-label="Photo crop area — drag to reposition"
               className="relative w-full overflow-hidden rounded-lg bg-slate-200
                          cursor-move select-none touch-none ring-2 ring-indigo-400"
               style={{ aspectRatio: `${ASPECT}` }}
               onPointerDown={onPointerDown}
               onPointerMove={onPointerMove}
               onPointerUp={endDrag}
               onPointerLeave={endDrag}
               onWheel={(e) => applyZoom(zoom - Math.sign(e.deltaY) * 0.15)}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={src} alt="Photo being cropped" draggable={false}
                 className="absolute top-0 left-0 max-w-none origin-top-left pointer-events-none"
                 style={scale ? {
                   width: scale.displayW, height: scale.displayH,
                   transform: `translate(${offset.ox}px, ${offset.oy}px)`,
                 } : undefined} />
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500">Zoom</span>
            <input type="range" min={1} max={MAX_ZOOM} step={0.01} value={zoom}
                   aria-label="Zoom"
                   onChange={(e) => applyZoom(Number(e.target.value))}
                   className="flex-1 accent-indigo-600" />
            <span className="text-xs text-slate-500 w-10 text-right tabular-nums">
              {zoom.toFixed(1)}×
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button type="button" onClick={confirmCrop} disabled={busy}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg
                         hover:bg-indigo-700 disabled:opacity-50">
              {busy ? "Uploading…" : "Use this crop"}
            </button>
            <button type="button" onClick={cancel} disabled={busy}
              className="px-4 py-2 bg-white text-slate-700 text-sm font-medium border
                         border-slate-300 rounded-lg hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
