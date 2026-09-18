import type { Metadata } from "next";
import Link from "next/link";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { fetchJson } from "@/lib/ssr";
import { labPagePath } from "@/lib/labs";
import type { LabIndexOut } from "@/types/api";
import { LabCardChip, LabCardCta } from "./LabCardChip";

export const metadata: Metadata = {
  title: "Interactive Labs & Visual Walkthroughs — CPMAI Exam Prep",
  description:
    "Hands-on labs and visual walkthroughs for CPMAI concepts: metrics, " +
    "thresholds, the data pipeline end to end, the Phase II & III activity " +
    "journey, the ML training pipeline and nested cross-validation.",
  alternates: { canonical: "/labs" },
};

const GROUPS: { key: LabIndexOut["group"]; title: string; lede: string }[] = [
  { key: "interactive", title: "Interactive labs",
    lede: "Concepts you can drag, not just read." },
  { key: "walkthrough", title: "Visual walkthroughs",
    lede: "The parts of CPMAI the exam tests at the application level, drawn end to end." },
];

/** Index of labs — registry-driven (backend app/core/labs_registry.py).
 *  A disabled lab's card is hidden and its page redirects here. Backend
 *  unreachable → the list is empty and a notice shows (fail open on the
 *  pages themselves, never a 500 here). */
export default async function LabsIndexPage() {
  const labs = (await fetchJson<LabIndexOut[]>("/content/labs", []))
    .filter(l => l.enabled);
  return (
    <>
      <SiteHeader active="labs" />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 py-10 min-h-[60vh]">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Interactive Labs</h1>
        <p className="text-slate-600 mb-8 max-w-2xl">
          Concepts you can drag, not just read — plus visual walkthroughs of
          the parts of CPMAI the exam loves to test at the application level.
        </p>
        {GROUPS.map(g => {
          const items = labs.filter(l => l.group === g.key);
          if (!items.length) return null;
          return (
            <section key={g.key} className="mb-10">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
                {g.title}
              </h2>
              <div className="grid sm:grid-cols-2 gap-5">
                {items.map(l => (
                  <Link
                    key={l.slug}
                    href={labPagePath(l.slug)}
                    className="block bg-white border border-slate-200 rounded-2xl p-6
                               hover:border-indigo-300 hover:shadow-md transition"
                  >
                    <div className="flex flex-wrap gap-2 mb-3">
                      <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700">
                        {l.domain}
                      </span>
                      <LabCardChip lab={l} />
                    </div>
                    <h3 className="font-semibold text-lg text-slate-900 mb-1">{l.title}</h3>
                    <p className="text-sm text-slate-600">{l.blurb}</p>
                    {l.mode !== "free" && l.plans.length > 0 && (
                      <p className="text-xs text-slate-500 mt-3">
                        Full access with: {l.plans.map(p => p.name).join(", ")}
                      </p>
                    )}
                    <LabCardCta lab={l} />
                  </Link>
                ))}
              </div>
            </section>
          );
        })}
        {labs.length === 0 && (
          <p className="text-slate-500 text-sm">
            Labs are temporarily offline — check back soon.
          </p>
        )}
      </main>
      <SiteFooter />
    </>
  );
}
