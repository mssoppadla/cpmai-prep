import type { Metadata } from "next";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { JsonLd } from "@/components/seo/JsonLd";
import { API, DEFAULT_REVALIDATE_S } from "@/lib/ssr";
import { sanitizeHtml } from "@/lib/sanitizeHtml";
import { MetricsLabClient } from "./MetricsLabClient";



export async function generateMetadata(): Promise<Metadata> {
  const copy = await loadTeachingCopy();
  return {
    title:
      `${copy.title} — Precision, Recall, Overfitting & AUC, Interactively`,
    description:
      "Diagnose machine-learning model errors hands-on: drag model " +
      "complexity, class balance and the decision threshold to see " +
      "precision, recall, the confusion matrix, bias–variance, ROC and " +
      "PR curves react live — with the remedy for every failure mode. " +
      "Built for CPMAI Domain IV, Model Evaluation.",
    alternates: { canonical: "/labs/metrics-lab" },
    openGraph: {
      title: `${copy.title} — CPMAI Interactive Lab`,
      description:
        "Underfitting, overfitting, the imbalance trap, threshold " +
        "trade-offs — see them, then fix them. Free, no login.",
      type: "website",
    },
  };
}

/** Built-in defaults — used when the admin settings are empty, so a
 *  wiped setting can never blank the page. Kept in sync with the
 *  seeded values in backend/seeds/default_settings.json. */
const DEFAULT_TAKEAWAY_HTML =
  "<b>1 · Compare models by the AUC number</b> (always on held-out " +
  "data): ~0.5 coin flip · 0.7–0.8 okay · 0.8–0.9 good · &gt;0.9 " +
  "excellent — or suspicious, check the Gap.<br>" +
  "<b>2 · Pick which AUC to read by class balance:</b> balanced → " +
  "AUC-ROC; rare positives → PR-AUC. If they disagree, believe " +
  "PR-AUC.<br>" +
  "<b>3 · Set the threshold from the curve's shape:</b> decide which " +
  "mistake costs more (FP vs FN), find that trade-off point, use its " +
  "threshold. The dot moves — <b>the AUC never does</b>: only a " +
  "better model lifts the curve.";

const DEFAULT_REFERENCE_HTML =
  "<table><thead><tr><th>You observe</th><th>Why</th>" +
  "<th>Consequence</th><th>Remedy</th></tr></thead><tbody>" +
  "<tr><td>Precision low, recall fine</td><td>Loose threshold / FP " +
  "flood</td><td>False alarms erode trust</td><td>Raise threshold; " +
  "rebalance</td></tr>" +
  "<tr><td>Recall low, precision fine</td><td>Strict threshold / rare " +
  "positives</td><td>Real cases slip through</td><td>Lower threshold; " +
  "oversample, class weights</td></tr>" +
  "<tr><td>Both low, train ≈ test</td><td>Underfit — high bias</td>" +
  "<td>Bad everywhere; threshold useless</td><td>More " +
  "features/capacity, boosting</td></tr>" +
  "<tr><td>Train great, test poor</td><td>Overfit — high variance</td>" +
  "<td>Accuracy drops on real data</td><td>Regularization, bagging, " +
  "more data, early stop</td></tr>" +
  "<tr><td>Both high (bias + variance)</td><td>Wrong model AND too " +
  "little data</td><td>Unreliable and wrong — worst case</td><td>More " +
  "data first, then grow capacity</td></tr>" +
  "<tr><td>Accuracy high, P or R low</td><td>Imbalance — negatives " +
  "dominate</td><td>Metric lies; model useless at its job</td>" +
  "<td>Judge by F1/PR-AUC; rebalance</td></tr></tbody></table>";

const DEFAULT_TITLE = "Classification Metrics Lab";

async function loadTeachingCopy(): Promise<{
  title: string; takeaway: string; reference: string;
}> {
  try {
    const r = await fetch(`${API}/content/labs/metrics-lab`, {
      next: { revalidate: DEFAULT_REVALIDATE_S },
    });
    if (r.ok) {
      const d = await r.json();
      return {
        title: (d.title || DEFAULT_TITLE).slice(0, 80),
        takeaway: sanitizeHtml(d.takeaway_html || DEFAULT_TAKEAWAY_HTML),
        reference: sanitizeHtml(d.reference_html || DEFAULT_REFERENCE_HTML),
      };
    }
  } catch { /* backend unreachable — defaults below */ }
  return {
    title: DEFAULT_TITLE,
    takeaway: sanitizeHtml(DEFAULT_TAKEAWAY_HTML),
    reference: sanitizeHtml(DEFAULT_REFERENCE_HTML),
  };
}

export default async function ModelErrorLabPage() {
  const copy = await loadTeachingCopy();
  return (
    <>
      <JsonLd data={{
        "@context": "https://schema.org",
        "@type": "LearningResource",
        name: copy.title,
        description:
          "Interactive lab for diagnosing classifier errors: " +
          "underfitting, overfitting, class imbalance and threshold " +
          "trade-offs, with precision, recall, confusion matrix, " +
          "bias-variance and ROC/PR curves updating live.",
        educationalLevel: "Professional certification preparation",
        learningResourceType: "Interactive simulation",
        teaches: [
          "Precision and recall", "Confusion matrix",
          "Overfitting and underfitting", "Bias-variance tradeoff",
          "ROC and precision-recall curves", "Class imbalance",
        ],
        isAccessibleForFree: true,
        provider: { "@type": "Organization", name: "CPMAI Exam Prep" },
      }} />
      <SiteHeader active="labs" />
      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-10">
        <p className="text-xs text-slate-500 mb-2">
          Labs → {copy.title}
        </p>
        <h1 className="text-3xl font-bold text-slate-900 mb-2">
          {copy.title}
        </h1>
        <p className="text-slate-600 mb-4 max-w-2xl">
          When is precision low? Why does accuracy lie on rare classes?
          What does overfitting look like on data the model never saw —
          and what actually fixes each failure? Drag three knobs and
          find out: every metric, both curves, the bias–variance target
          and a live diagnosis with its remedy.
        </p>
        <div className="flex flex-wrap gap-2 mb-6">
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full
                           bg-indigo-50 text-indigo-700">
            D-IV · Model Evaluation
          </span>
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full
                           bg-emerald-50 text-emerald-700">
            Interactive — no login needed
          </span>
          <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full
                           bg-amber-50 text-amber-800">
            ~10 min
          </span>
        </div>
        <MetricsLabClient
          takeawayHtml={copy.takeaway}
          referenceHtml={copy.reference}
        />
      </main>
      <SiteFooter />
    </>
  );
}
