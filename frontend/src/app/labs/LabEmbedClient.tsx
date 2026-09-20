"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { content } from "@/lib/api";
import { trackCta } from "@/lib/tracker";
import { labEmbedUrl } from "@/lib/labs";
import type { LabAccessOut } from "@/types/api";

/** Access chip shown on the lab page and on the /labs cards. */
export function accessChip(a: Pick<LabAccessOut, "mode" | "full" | "reason" | "free_upto_index" | "sections">) {
  if (a.mode === "free") return { label: "Free", tone: "em" as const };
  if (a.full) return { label: "Included in your plan", tone: "em" as const };
  if (a.mode === "signin") return { label: "Free account required", tone: "am" as const };
  if (a.mode === "preview") {
    const n = a.free_upto_index + 1;
    return { label: `Free preview · ${n} of ${a.sections.length} sections`, tone: "am" as const };
  }
  return { label: "🔒 Plan members", tone: "vi" as const };
}

const TONE: Record<"em" | "am" | "vi", string> = {
  em: "bg-emerald-50 text-emerald-700",
  am: "bg-amber-50 text-amber-800",
  vi: "bg-violet-50 text-violet-700",
};

export function AccessChip({ a }: { a: Parameters<typeof accessChip>[0] }) {
  const c = accessChip(a);
  return (
    <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${TONE[c.tone]}`}>
      {c.label}
    </span>
  );
}

/**
 * Embeds a lab asset through /labs/embed/<slug>.
 *
 *  1. Asks the backend what THIS visitor may see (Bearer token attached
 *     when the browser has one) and gets a short-lived embed token.
 *  2. Loads the iframe with that token; the embed route serves the
 *     asset cut at the decision. If the access call fails the iframe
 *     loads anonymously — the embed route decides again server-side.
 *  3. Sizes the frame per the lab's frame mode and records a CTA event
 *     when the lock panel is shown.
 *
 *  Frame modes (registry `frame`):
 *   - "content": the frame grows to the document's reported height
 *     (lab-height messages) so the PAGE scrolls as one document. Right
 *     for infographics with no sticky UI.
 *   - "viewport": the frame fills the viewport and the DOCUMENT scrolls
 *     inside it, like a standalone page. Sticky rails, fixed buttons,
 *     popovers and in-page navigation all need a viewport of their own;
 *     a content-sized frame has none (2026-09-18: rail scrolled away,
 *     back-pill landed 20,000 px down, expand/collapse "stuck" while
 *     the height message lagged).
 */
export function LabEmbedClient({
  slug, title, pagePath, ledes, fullscreenLink = true, frame = "content",
}: {
  slug: string;
  title: string;
  pagePath: string;
  /** Simulator-only: per-stage copy overrides posted into the iframe. */
  ledes?: Record<string, string>;
  fullscreenLink?: boolean;
  frame?: "content" | "viewport";
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(1100);
  const [access, setAccess] = useState<LabAccessOut | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const viewport = frame === "viewport";

  // viewport mode: fill the window below the frame's top edge, and keep
  // a small margin so the page's own bottom edge stays reachable.
  useEffect(() => {
    if (!viewport) return;
    function fit() {
      const top = frameRef.current?.getBoundingClientRect().top ?? 0;
      // when the frame sits below the header, leave room for it; once the
      // user has scrolled the page so the frame is at the top, use the
      // whole window
      const avail = window.innerHeight - Math.max(0, Math.min(top, 96)) - 16;
      setHeight(Math.max(560, Math.floor(avail)));
    }
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [viewport]);

  useEffect(() => {
    let alive = true;
    content.labAccess(slug)
      .then(a => { if (!alive) return; setAccess(a); setSrc(labEmbedUrl(slug, a.embed_token)); })
      .catch(() => { if (alive) setSrc(labEmbedUrl(slug)); });
    return () => { alive = false; };
  }, [slug]);

  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      if (ev.origin !== window.location.origin) return;
      const d = ev.data;
      if (!d || typeof d !== "object") return;
      if ((d.type === "lab-height" || d.type === "dpn-height" || d.type === "dpn2-height")
          && typeof d.h === "number") {
        if (!viewport) setHeight(Math.min(60000, Math.max(600, Math.ceil(d.h))));
      } else if (d.type === "lab-lock") {
        trackCta("lab_lock_shown", { lab: slug, locked: Number(d.locked) || 0 });
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [slug, viewport]);

  function onLoad() {
    if (ledes && Object.keys(ledes).length) {
      frameRef.current?.contentWindow?.postMessage(
        { type: "dpn-ledes", ledes }, window.location.origin);
    }
  }

  return (
    <div>
      {(access || fullscreenLink) && (
        <div className="flex flex-wrap items-center gap-2 mb-4">
          {access && <AccessChip a={access} />}
          {access && !access.full && access.reason === "plan" && access.plans.length > 0 && (
            <span className="text-xs text-slate-500">
              Full access with:{" "}
              {access.plans.map((p, i) => (
                <span key={p.slug}>
                  {i > 0 && ", "}
                  <Link href="/pricing" className="text-indigo-600 hover:underline">{p.name}</Link>
                </span>
              ))}
            </span>
          )}
          {fullscreenLink && src && (
            <a href={src} target="_blank" rel="noopener"
               className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-700 hover:bg-slate-200">
              Open full screen ↗
            </a>
          )}
        </div>
      )}
      {src ? (
        <iframe
          ref={frameRef}
          src={src}
          title={title}
          onLoad={onLoad}
          style={{ height }}
          // "auto" (not "no") in content mode too: after a browser zoom the
          // fit-once documents are wider than the frame and must scroll
          // sideways; the tracked height keeps a vertical bar from appearing
          scrolling={viewport ? "yes" : "auto"}
          className="w-full border border-slate-200 rounded-2xl bg-white"
        />
      ) : (
        <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center text-slate-400">
          Loading…
        </div>
      )}
    </div>
  );
}
