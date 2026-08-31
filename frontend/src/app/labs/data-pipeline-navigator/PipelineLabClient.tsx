"use client";

import { useEffect, useRef, useState } from "react";

/** Embeds the self-contained Data Pipeline Navigator simulator
 *  (/labs/pipeline-sim.html) and wires it to the admin-editable copy:
 *  - posts the per-stage description overrides into the iframe;
 *  - listens for the iframe's height reports so the page scrolls as one
 *    document (no inner scrollbar). */
export function PipelineLabClient({
  stageLedes,
}: {
  stageLedes: Record<string, string>;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(900);

  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      const d = ev.data;
      if (d && d.type === "dpn-height" && typeof d.h === "number") {
        // clamp: never collapse, never runaway
        setHeight(Math.min(20000, Math.max(600, Math.ceil(d.h))));
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  function pushOverrides() {
    if (!Object.keys(stageLedes).length) return;
    frameRef.current?.contentWindow?.postMessage(
      { type: "dpn-ledes", ledes: stageLedes },
      window.location.origin,
    );
  }

  return (
    <iframe
      ref={frameRef}
      src="/labs/pipeline-sim.html?v=3"
      title="Data Pipeline Navigator simulator"
      onLoad={pushOverrides}
      style={{ height }}
      className="w-full border border-slate-200 rounded-2xl bg-white"
    />
  );
}
