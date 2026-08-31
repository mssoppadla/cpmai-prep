import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { JsonLd } from "@/components/seo/JsonLd";
import { API, DEFAULT_REVALIDATE_S } from "@/lib/ssr";
import { sanitizeHtml } from "@/lib/sanitizeHtml";
import { PipelineLabClient } from "./PipelineLabClient";

/** Built-in defaults — used when the admin settings are empty, so a
 *  wiped setting can never blank the page. Kept in sync with the
 *  seeded values in backend/seeds/default_settings.json. */
const DEFAULT_TITLE = "Data Pipeline Navigator";

type PipelineCopy = {
  title: string;
  introHtml: string;
  takeawayHtml: string;
  stageLedes: Record<string, string>;
  enabled: boolean;
};

async function loadCopy(): Promise<PipelineCopy> {
  try {
    const r = await fetch(`${API}/content/labs/data-pipeline-navigator`, {
      next: { revalidate: DEFAULT_REVALIDATE_S },
    });
    if (r.ok) {
      const d = await r.json();
      const ledes: Record<string, string> = {};
      if (d.stage_ledes && typeof d.stage_ledes === "object") {
        for (const [k, v] of Object.entries(d.stage_ledes)) {
          if (typeof v === "string" && v.trim()) ledes[k] = v;
        }
      }
      return {
        enabled: d.enabled !== false,
        title: (d.title || DEFAULT_TITLE).slice(0, 80),
        introHtml: d.intro_html ? sanitizeHtml(d.intro_html) : "",
        takeawayHtml: d.takeaway_html ? sanitizeHtml(d.takeaway_html) : "",
        stageLedes: ledes,
      };
    }
  } catch { /* backend unreachable — defaults below (fail open) */ }
  return { title: DEFAULT_TITLE, introHtml: "", takeawayHtml: "",
           stageLedes: {}, enabled: true };
}

export async function generateMetadata(): Promise<Metadata> {
  const copy = await loadCopy();
  return {
    title:
      `${copy.title} — Run a CPMAI Data Project End to End, Interactively`,
    description:
      "Walk a fraud-detection project through the CPMAI data lifecycle: " +
      "profile the 4 V's, pick an integration framework, validate at the " +
      "source, govern lineage, label data, size it against the curse of " +
      "dimensionality, run EDA, cleanse, encode, fix class imbalance and " +
      "split — every decision carries into the next stage.",
    alternates: { canonical: "/labs/data-pipeline-navigator" },
    openGraph: {
      title: `${copy.title} — CPMAI Interactive Lab`,
      description:
        "Twelve live simulations, one continuous project: from raising " +
        "data access to a generated data-readiness report. Free, no login.",
      type: "website",
    },
  };
}

export default async function DataPipelineNavigatorPage() {
  const copy = await loadCopy();
  if (!copy.enabled) redirect("/labs");
  return (
    <>
      <JsonLd data={{
        "@context": "https://schema.org",
        "@type": "LearningResource",
        name: copy.title,
        description:
          "Interactive simulator of CPMAI Phases II-III: data profiling " +
          "(4 V's, quality dimensions, representativeness), integration " +
          "frameworks, source validation, lineage, labelling strategies, " +
          "the curse of dimensionality, EDA, cleansing, encoding, class " +
          "imbalance (SMOTE) and train/validation/test splitting.",
        educationalLevel: "Professional certification preparation",
        learningResourceType: "Interactive simulation",
        teaches: [
          "The 4 V's of big data", "Data quality dimensions",
          "Data integration frameworks", "Reconciliation and checksums",
          "Data lineage", "Data labelling", "Curse of dimensionality",
          "Exploratory Data Analysis", "Target encoding",
          "SMOTE and class imbalance", "Data splitting and leakage",
        ],
        isAccessibleForFree: true,
        provider: { "@type": "Organization", name: "CPMAI Exam Prep" },
      }} />
      <SiteHeader active="labs" />
      <main className="max-w-[1400px] mx-auto px-4 sm:px-6 py-8 sm:py-10">
        <p className="text-xs text-slate-500 mb-2">
          Labs → {copy.title}
        </p>
        <h1 className="text-3xl font-bold text-slate-900 mb-2">
          {copy.title}
        </h1>
        <p className="text-slate-600 mb-4 max-w-3xl">
          One continuous fraud-detection project across twelve live
          simulations: profile the incoming stream, choose how sources
          integrate, validate collection while the source still exists,
          govern lineage, label the data, size it, explore it, cleanse
          it, encode it, balance it and split it — every decision you
          make follows the project into the next stage, and it ends
          with a generated data-readiness report.
        </p>
        <div className="flex flex-wrap gap-2 mb-6">
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full
                           bg-indigo-50 text-indigo-700">
            D-III · Data Understanding &amp; Preparation
          </span>
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full
                           bg-amber-50 text-amber-800">
            ~25 min
          </span>
          <a
            href="/labs/pipeline-sim.html?v=3"
            target="_blank"
            rel="noopener"
            className="text-xs font-semibold px-2.5 py-0.5 rounded-full
                       bg-slate-100 text-slate-700 hover:bg-slate-200"
          >
            Open full screen ↗
          </a>
        </div>
        {copy.introHtml ? (
          <div
            className="prose prose-sm max-w-3xl mb-6 text-slate-700"
            dangerouslySetInnerHTML={{ __html: copy.introHtml }}
          />
        ) : null}
        <PipelineLabClient stageLedes={copy.stageLedes} />
        {copy.takeawayHtml ? (
          <div
            className="prose prose-sm max-w-3xl mt-6 text-slate-700"
            dangerouslySetInnerHTML={{ __html: copy.takeawayHtml }}
          />
        ) : null}
      </main>
      <SiteFooter />
    </>
  );
}
