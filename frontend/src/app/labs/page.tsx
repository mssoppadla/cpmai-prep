import type { Metadata } from "next";
import Link from "next/link";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";

export const metadata: Metadata = {
  title: "Interactive Labs — CPMAI Exam Prep",
  description:
    "Hands-on interactive labs for CPMAI concepts: play with thresholds, " +
    "confusion matrices, ROC and precision-recall curves.",
  alternates: { canonical: "/labs" },
};

/** Index of interactive labs. One lab today; the grid is ready for more. */
export default function LabsIndexPage() {
  return (
    <>
      <SiteHeader active="labs" />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 py-10 min-h-[60vh]">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Interactive Labs</h1>
        <p className="text-slate-600 mb-8 max-w-2xl">
          Concepts you can drag, not just read. Each lab targets a topic the
          CPMAI exam loves to test at the application level.
        </p>
        <div className="grid sm:grid-cols-2 gap-5">
          <Link
            href="/labs/metrics-lab"
            className="block bg-white border border-slate-200 rounded-2xl p-6
                       hover:border-indigo-300 hover:shadow-md transition"
          >
            <div className="flex gap-2 mb-3">
              <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700">
                D-IV · Model Evaluation
              </span>
              <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700">
                No login needed
              </span>
            </div>
            <h2 className="font-semibold text-lg text-slate-900 mb-1">
              Classification Metrics Lab
            </h2>
            <p className="text-sm text-slate-600">
              Underfitting, overfitting, the imbalance trap — trigger each
              failure mode, watch train vs test data, the bias–variance
              target and both AUC curves react, and learn the remedy.
            </p>
            <span className="inline-block mt-4 text-sm font-medium text-indigo-600">
              Open the lab →
            </span>
          </Link>
          <Link
            href="/labs/data-pipeline-navigator"
            className="block bg-white border border-slate-200 rounded-2xl p-6
                       hover:border-indigo-300 hover:shadow-md transition"
          >
            <div className="flex gap-2 mb-3">
              <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700">
                D-III · Data Understanding &amp; Preparation
              </span>
              <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700">
                No login needed
              </span>
            </div>
            <h2 className="font-semibold text-lg text-slate-900 mb-1">
              Data Pipeline Navigator
            </h2>
            <p className="text-sm text-slate-600">
              Run one fraud-detection project through the whole CPMAI data
              lifecycle — profile the 4 V&apos;s, validate at the source,
              govern lineage, label, size, explore, cleanse, encode,
              balance and split. Twelve live simulations; every decision
              carries forward into a generated readiness report.
            </p>
            <span className="inline-block mt-4 text-sm font-medium text-indigo-600">
              Open the lab →
            </span>
          </Link>
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
