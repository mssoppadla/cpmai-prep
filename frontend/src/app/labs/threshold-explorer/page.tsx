import type { Metadata } from "next";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { ThresholdExplorerClient } from "./ThresholdExplorerClient";

export const metadata: Metadata = {
  title: "Threshold Explorer — CPMAI Interactive Lab",
  description:
    "Drag the classification threshold and watch every case re-classify: " +
    "precision, recall, the confusion matrix, ROC and PR curves recompute " +
    "live. Built for CPMAI Domain IV — Model Evaluation.",
  alternates: { canonical: "/labs/threshold-explorer" },
};

export default function ThresholdExplorerPage() {
  return (
    <>
      <SiteHeader active="labs" />
      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-10">
        <p className="text-xs text-slate-500 mb-2">Labs → Threshold Explorer</p>
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Threshold Explorer</h1>
        <p className="text-slate-600 mb-4 max-w-2xl">
          Drag the threshold and watch every case re-classify — precision,
          recall, the confusion matrix and both curves recompute live.
          Choosing an operating point is a <em>business</em> decision, not a
          math one.
        </p>
        <div className="flex flex-wrap gap-2 mb-6">
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700">
            D-IV · Model Evaluation
          </span>
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700">
            Interactive — no login needed
          </span>
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-800">
            ~5 min
          </span>
        </div>
        <ThresholdExplorerClient />
      </main>
      <SiteFooter />
    </>
  );
}
