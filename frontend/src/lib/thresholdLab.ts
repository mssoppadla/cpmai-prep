/**
 * Pure math for the Threshold Explorer lab (/labs/threshold-explorer).
 *
 * Kept out of the page component so the classification, ROC and
 * Precision–Recall computations are unit-testable. Mirrors the maths of
 * the original standalone page: trapezoidal ROC-AUC, step-wise average
 * precision (sklearn's average_precision_score).
 */

export interface LabCase { score: number; actual: 0 | 1 }

export interface Counts { TP: number; FP: number; FN: number; TN: number }

export interface Metrics {
  precision: number; recall: number; accuracy: number; f1: number;
}

/** Classify every case at threshold t (predicted positive when
 *  score >= t) and tally the confusion matrix. */
export function countsAt(cases: LabCase[], t: number): Counts {
  let TP = 0, FP = 0, FN = 0, TN = 0;
  for (const c of cases) {
    const p = c.score >= t;
    if (c.actual === 1) { if (p) TP++; else FN++; }
    else { if (p) FP++; else TN++; }
  }
  return { TP, FP, FN, TN };
}

export function metricsOf(c: Counts): Metrics {
  const tot = c.TP + c.FP + c.FN + c.TN || 1;
  const precision = c.TP + c.FP ? c.TP / (c.TP + c.FP) : 0;
  const recall = c.TP + c.FN ? c.TP / (c.TP + c.FN) : 0;
  const accuracy = (c.TP + c.TN) / tot;
  const f1 = precision + recall
    ? (2 * precision * recall) / (precision + recall) : 0;
  return { precision, recall, accuracy, f1 };
}

/** ROC points (sorted by FPR) + trapezoidal AUC. Needs both classes. */
export function rocCurve(cases: LabCase[]): {
  points: Array<{ fpr: number; tpr: number }>; auc: number;
} {
  const NP = cases.filter((c) => c.actual === 1).length;
  const NN = cases.length - NP;
  if (NP === 0 || NN === 0) return { points: [], auc: 0 };
  const cuts = Array.from(new Set(cases.map((c) => c.score).concat([0, 1.01])))
    .sort((a, b) => b - a);
  const points = [{ fpr: 0, tpr: 0 }];
  for (const t of cuts) {
    const c = countsAt(cases, t);
    points.push({ fpr: c.FP / NN, tpr: c.TP / NP });
  }
  points.push({ fpr: 1, tpr: 1 });
  points.sort((a, b) => a.fpr - b.fpr || a.tpr - b.tpr);
  let auc = 0;
  for (let i = 1; i < points.length; i++) {
    auc += (points[i].fpr - points[i - 1].fpr) *
           (points[i].tpr + points[i - 1].tpr) / 2;
  }
  return { points, auc };
}

/** Precision–Recall points (threshold descending → recall ascending) +
 *  step-wise average precision. Also reports prevalence (the PR
 *  baseline). Needs both classes. */
export function prCurve(cases: LabCase[]): {
  points: Array<{ rec: number; prec: number }>; ap: number; prevalence: number;
} {
  const NP = cases.filter((c) => c.actual === 1).length;
  const NN = cases.length - NP;
  const prevalence = cases.length ? NP / cases.length : 0;
  if (NP === 0 || NN === 0) return { points: [], ap: 0, prevalence };
  const cuts = Array.from(new Set(cases.map((c) => c.score)))
    .sort((a, b) => b - a);
  const seq: Array<{ rec: number; prec: number }> = [];
  for (const t of cuts) {
    const c = countsAt(cases, t);
    if (c.TP + c.FP === 0) continue;
    seq.push({ rec: c.TP / NP, prec: c.TP / (c.TP + c.FP) });
  }
  let ap = 0, prevR = 0;
  for (const p of seq) { ap += (p.rec - prevR) * p.prec; prevR = p.rec; }
  return { points: [{ rec: 0, prec: 1 }, ...seq], ap, prevalence };
}

/** Parse the admin textarea format — one case per line, "score, actual"
 *  — into cases plus per-line errors (1-indexed line numbers). */
export function parseCasesText(text: string): {
  cases: LabCase[]; errors: Array<{ line: number; text: string }>;
} {
  const cases: LabCase[] = [];
  const errors: Array<{ line: number; text: string }> = [];
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = raw.trim();
    if (!line || line.startsWith("#")) return;
    const m = line.match(/^([0-9]*\.?[0-9]+)\s*,\s*([01])\s*$/);
    const score = m ? parseFloat(m[1]) : NaN;
    if (!m || !(score >= 0 && score <= 1)) {
      errors.push({ line: i + 1, text: raw });
      return;
    }
    cases.push({ score, actual: parseInt(m[2], 10) as 0 | 1 });
  });
  return { cases, errors };
}

export function casesToText(cases: LabCase[]): string {
  return cases.map((c) => `${c.score}, ${c.actual}`).join("\n");
}
