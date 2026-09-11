import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { API, DEFAULT_REVALIDATE_S } from "@/lib/ssr";
import { Dpn2Client } from "./Dpn2Client";

/** Built-in default — used when the admin setting is empty. */
const DEFAULT_TITLE = "Data Pipeline Navigator 2";

type Dpn2Copy = { title: string; enabled: boolean };

async function loadCopy(): Promise<Dpn2Copy> {
  try {
    const r = await fetch(`${API}/content/labs/data-pipeline-navigator-2`, {
      next: { revalidate: DEFAULT_REVALIDATE_S },
    });
    if (r.ok) {
      const d = await r.json();
      return {
        enabled: d.enabled !== false,
        title: (d.title || DEFAULT_TITLE).slice(0, 80),
      };
    }
  } catch { /* backend unreachable — fail open, defaults below */ }
  return { title: DEFAULT_TITLE, enabled: true };
}

export async function generateMetadata(): Promise<Metadata> {
  const copy = await loadCopy();
  return {
    title: `${copy.title} — The Phase II & III Activity Journey`,
    description:
      "Run CPMAI Phases II and III end to end the way an enterprise AI " +
      "program does: 22 stations from identifying data SMEs to Operate, " +
      "with roles, a clinic-chatbot worked example, two decision gates, " +
      "the Phase III master sequence (Govern → Extract → Load → Cleanse " +
      "→ Filter → Label → Split → Balance → Features → Gate → Operate), " +
      "and 300+ tap-to-explain terms.",
    alternates: { canonical: "/labs/data-pipeline-navigator-2" },
    robots: { index: false },   // member content — keep out of search
  };
}

export default async function Dpn2Page() {
  const copy = await loadCopy();
  if (!copy.enabled) redirect("/labs");
  return (
    <>
      <SiteHeader active="labs" />
      <main className="max-w-[1400px] mx-auto px-4 sm:px-6 py-8 sm:py-10">
        <p className="text-xs text-slate-500 mb-2">Labs → {copy.title}</p>
        <h1 className="text-3xl font-bold text-slate-900 mb-2">{copy.title}</h1>
        <p className="text-slate-600 mb-4 max-w-3xl">
          The complete Phase II &amp; III journey as it runs inside a real
          enterprise AI program — every activity with its owner, one
          continuous clinic-chatbot example, two go/no-go gates, the
          Phase III master sequence, and a glossary popover on every
          technical term. The twelve interactive playgrounds of the
          original Navigator are linked from the stations where they
          belong.
        </p>
        <div className="flex flex-wrap gap-2 mb-6">
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700">
            D-III · Data Understanding &amp; Preparation
          </span>
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-800">
            ~45 min · reference-grade
          </span>
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700">
            Logged-in learners
          </span>
        </div>
        <Dpn2Client />
      </main>
      <SiteFooter />
    </>
  );
}
