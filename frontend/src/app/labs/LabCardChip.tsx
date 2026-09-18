"use client";

import { useEffect, useState } from "react";
import { content } from "@/lib/api";
import type { LabAccessOut, LabIndexOut } from "@/types/api";
import { AccessChip } from "./LabEmbedClient";

type Known = Parameters<typeof AccessChip>[0]["a"];

function anonymousView(lab: LabIndexOut): Known {
  return {
    mode: lab.mode, full: lab.mode === "free", reason: "ok",
    free_upto_index: lab.free_upto_index, sections: lab.sections,
  };
}

// One access lookup per lab per page load, shared by the chip and the
// call-to-action on the same card.
const pending = new Map<string, Promise<LabAccessOut>>();
function lookup(slug: string): Promise<LabAccessOut> {
  let p = pending.get(slug);
  if (!p) { p = content.labAccess(slug); pending.set(slug, p); }
  return p;
}

function useCardAccess(lab: LabIndexOut): Known {
  const [a, setA] = useState<Known>(() => anonymousView(lab));
  useEffect(() => {
    if (lab.mode === "free") return;
    let has = false;
    try { has = Boolean(window.localStorage.getItem("cpmai.access")); } catch { /* private mode */ }
    if (!has) return;
    let alive = true;
    lookup(lab.slug).then(r => { if (alive) setA(r); }).catch(() => {});
    return () => { alive = false; };
  }, [lab]);
  return a;
}

/** Access chip on a /labs card. Server-rendered from the anonymous
 *  view; when the browser holds a login token and the lab is gated, it
 *  re-checks so a plan member sees "Included in your plan". */
export function LabCardChip({ lab }: { lab: LabIndexOut }) {
  return <AccessChip a={useCardAccess(lab)} />;
}

/** The card's call-to-action, consistent with the chip. */
export function LabCardCta({ lab }: { lab: LabIndexOut }) {
  const a = useCardAccess(lab);
  const label = a.full || a.mode === "preview" ? "Open the lab →"
    : a.mode === "signin" ? "Sign in to open →" : "See plans →";
  return (
    <span className="inline-block mt-4 text-sm font-medium text-indigo-600">{label}</span>
  );
}
