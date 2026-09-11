"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

/** Auth-gated embed for Data Pipeline Navigator 2 (/labs/dpn-v2.html).
 *
 *  - Requires a logged-in user (the page is a member benefit): with no
 *    access token in localStorage we show a sign-in prompt instead of
 *    the lab. Client-side gating is deliberate — the asset itself has
 *    no sensitive data; the gate shapes the product, not security.
 *  - Listens for the iframe's height reports (dpn2-height) so the page
 *    scrolls as one document, same contract as the v1 simulator. */
export function Dpn2Client() {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(1200);
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    try {
      setAuthed(Boolean(window.localStorage.getItem("cpmai.access")));
    } catch {
      setAuthed(false);
    }
  }, []);

  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      const d = ev.data;
      if (d && d.type === "dpn2-height" && typeof d.h === "number") {
        setHeight(Math.min(40000, Math.max(800, Math.ceil(d.h))));
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  if (authed === null) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center text-slate-400">
        Loading…
      </div>
    );
  }

  if (!authed) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center">
        <div className="text-3xl mb-2">🔒</div>
        <h2 className="text-lg font-semibold text-slate-900 mb-1">
          Sign in to open this lab
        </h2>
        <p className="text-sm text-slate-600 max-w-md mx-auto mb-5">
          Data Pipeline Navigator 2 — the full Phase II &amp; III activity
          journey with roles, decisions, gates and 300+ tap-to-explain
          terms — is available to logged-in learners.
        </p>
        <Link
          href="/login?next=/labs/data-pipeline-navigator-2"
          className="inline-block px-5 py-2.5 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700"
        >
          Sign in / create a free account
        </Link>
      </div>
    );
  }

  return (
    <iframe
      ref={frameRef}
      src="/labs/dpn-v2.html?v=2"
      title="Data Pipeline Navigator 2"
      style={{ height }}
      className="w-full border border-slate-200 rounded-2xl bg-white"
    />
  );
}
