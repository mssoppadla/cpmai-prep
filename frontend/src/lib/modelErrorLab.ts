/**
 * Model Error Lab — simulation + diagnosis math (pure, unit-tested).
 *
 * The lab simulates a binary classifier as two Gaussian score
 * distributions on a 0..1 axis: negatives centered below 0.5,
 * positives above, separated by how well the model FIT the data.
 *
 *   - complexity drives separation: too simple → small separation
 *     (underfit, high bias); past the sweet spot the TRAIN separation
 *     keeps growing while the TEST separation shrinks (overfit — the
 *     train−test gap).
 *   - sample size drives stability: small samples add VARIANCE (an
 *     unstable fit), never bias.
 *   - threshold/prevalence pick the operating point; they never touch
 *     bias or variance (that asymmetry is itself a lesson).
 *
 * All rendering lives in the client component; everything here is
 * deterministic (quantile sampling, no RNG) so tests can pin exact
 * counts.
 */

export const SD = 0.13;
/** Best separation an honestly-fit model reaches (top of the
 *  no-overfit complexity range) — the bias anchor. */
export const SEP_BEST = 0.43;
export const SEP_MIN = 0.10;

export interface Seps { train: number; test: number; gap: number }

export function seps(complexity: number): Seps {
  const c = Math.min(100, Math.max(0, complexity));
  const train = SEP_MIN + 0.55 * (c / 100);
  const gap = c > 60 ? 0.55 * ((c - 60) / 40) : 0;
  return { train, test: Math.max(0.06, train - gap), gap: Math.max(0, gap) };
}

/** Abramowitz–Stegun normal CDF approximation (|err| < 8e-8). */
export function normCdf(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989423 * Math.exp((-x * x) / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478
    + t * (-1.821256 + t * 1.330274))));
  return x > 0 ? 1 - p : p;
}

export function normQuantile(p: number): number {
  let lo = -4, hi = 4;
  for (let i = 0; i < 40; i++) {
    const m = (lo + hi) / 2;
    if (normCdf(m) < p) lo = m; else hi = m;
  }
  return (lo + hi) / 2;
}

export interface LabPoint { score: number; isPos: boolean }
export interface LabSample { pos: LabPoint[]; neg: LabPoint[] }

/** Deterministic quantile sample: n points per class placed at the
 *  (i+0.5)/n quantiles of that class's distribution — so tail cases
 *  appear exactly when their probability mass warrants a point, and
 *  the drawn dots always reconcile with the tallied matrix. */
export function sample(N: number, prevalence: number, sep: number): LabSample {
  const nPos = Math.max(1, Math.round(N * prevalence));
  const nNeg = N - nPos;
  const mn = 0.5 - sep / 2, mp = 0.5 + sep / 2;
  const mk = (n: number, mu: number, isPos: boolean): LabPoint[] =>
    Array.from({ length: n }, (_, i) => ({
      score: Math.max(0.015, Math.min(0.985,
        mu + SD * normQuantile((i + 0.5) / n))),
      isPos,
    }));
  return { pos: mk(nPos, mp, true), neg: mk(nNeg, mn, false) };
}

export interface Counts { TP: number; FN: number; FP: number; TN: number }

export function tally(smp: LabSample, threshold: number): Counts {
  let TP = 0, FN = 0, FP = 0, TN = 0;
  smp.pos.forEach((d) => (d.score >= threshold ? TP++ : FN++));
  smp.neg.forEach((d) => (d.score >= threshold ? FP++ : TN++));
  return { TP, FN, FP, TN };
}

export interface Metrics {
  precision: number; recall: number; f1: number; accuracy: number;
}

export function metricsOf(c: Counts): Metrics {
  const n = c.TP + c.FN + c.FP + c.TN;
  const precision = c.TP + c.FP ? c.TP / (c.TP + c.FP) : 0;
  const recall = c.TP + c.FN ? c.TP / (c.TP + c.FN) : 0;
  const f1 = precision + recall
    ? (2 * precision * recall) / (precision + recall) : 0;
  return { precision, recall, f1, accuracy: n ? (c.TP + c.TN) / n : 0 };
}

/** Continuous TPR/FPR at a threshold for the given separation. */
export function rates(sep: number, threshold: number) {
  const mn = 0.5 - sep / 2, mp = 0.5 + sep / 2;
  return {
    fpr: 1 - normCdf((threshold - mn) / SD),
    tpr: 1 - normCdf((threshold - mp) / SD),
  };
}

export interface CurvePoint { x: number; y: number }
export interface Curves {
  roc: CurvePoint[]; pr: CurvePoint[]; aucRoc: number; aucPr: number;
}

/** Sweep every threshold: ROC (fpr,tpr) + PR (recall,precision) with
 *  trapezoid AUCs. Depends only on the TEST separation + prevalence —
 *  deliberately not on the chosen threshold. */
export function curves(sepTest: number, prevalence: number): Curves {
  const roc: CurvePoint[] = [], pr: CurvePoint[] = [];
  let aucRoc = 0, aucPr = 0;
  let prevR: CurvePoint | null = null, prevP: CurvePoint | null = null;
  for (let i = 0; i <= 200; i++) {
    const t = 1.2 - (i / 200) * 1.4;
    const r = rates(sepTest, t);
    const tpMass = prevalence * r.tpr;
    const fpMass = (1 - prevalence) * r.fpr;
    const prec = tpMass + fpMass > 1e-9 ? tpMass / (tpMass + fpMass) : 1;
    const rp = { x: r.fpr, y: r.tpr };
    const pp = { x: r.tpr, y: prec };
    if (prevR) aucRoc += (rp.x - prevR.x) * (rp.y + prevR.y) / 2;
    if (prevP) aucPr += (pp.x - prevP.x) * (pp.y + prevP.y) / 2;
    roc.push(rp); pr.push(pp);
    prevR = rp; prevP = pp;
  }
  return {
    roc, pr,
    aucRoc: Math.min(1, Math.max(0, aucRoc)),
    aucPr: Math.min(1, Math.max(0, aucPr)),
  };
}

/** Small samples make the FIT unstable — variance, never bias.
 *  20 cases is genuinely tiny, so it lands in the HIGH band on its
 *  own — that's what makes the high-bias + high-variance "worst
 *  corner" reachable (too-simple model + too-little data). */
export function smallNVariance(N: number): number {
  return N <= 20 ? 0.6 : N <= 50 ? 0.3 : N <= 100 ? 0.12 : 0;
}

export interface BiasVariance { bias: number; variance: number }

export function biasVariance(complexity: number, N: number): BiasVariance {
  const s = seps(complexity);
  return {
    bias: Math.min(1, Math.max(0,
      (SEP_BEST - s.train) / (SEP_BEST - SEP_MIN))),
    variance: Math.min(1, s.gap / 0.55 + smallNVariance(N)),
  };
}

export function bandOf(v: number, lo: number, hi: number):
  "low" | "medium" | "HIGH" {
  return v < lo ? "low" : v < hi ? "medium" : "HIGH";
}

export type Severity = "ok" | "info" | "bad";
export interface DiagMessage { html: string; info?: boolean }
export interface Diagnosis {
  severity: Severity;
  label: string;
  /** id of the reference-table row to highlight, if any */
  refRow: string | null;
  messages: DiagMessage[];
}

export interface DiagInput {
  N: number; complexity: number; prevalence: number;
  metrics: Metrics; counts: Counts;
  trainAccuracy: number; aucRoc: number; aucPr: number;
}

const pctS = (x: number) => (100 * x).toFixed(1) + "%";

/** The teaching brain: names the condition, the mechanism, and the
 *  remedy — in priority order, mirroring the reference table. */
export function diagnose(inp: DiagInput): Diagnosis {
  const { N, complexity: c, prevalence: p, metrics: m, counts } = inp;
  const gap = inp.trainAccuracy - m.accuracy;
  const bv = biasVariance(c, N);
  const messages: DiagMessage[] = [];
  let severity: Severity = "ok", label = "healthy",
    refRow: string | null = null;

  if (N <= 20 && m.accuracy >= 0.999) {
    messages.push({ info: true, html:
      `<b>Small-sample illusion.</b> 100% on ${N} cases proves little — ` +
      `raise Cases per set and the true error rate appears.` });
    severity = "info"; label = "unproven";
  }
  const bothHigh = bv.bias >= 0.6 && bv.variance >= 0.6;
  if (bothHigh) {
    messages.push({ html:
      `<b>Worst case — high bias AND high variance.</b> Too simple to ` +
      `learn the pattern AND too little data to learn it stably. Remedy ` +
      `IN ORDER: more data first (kills variance), then ` +
      `capacity/features (kills bias).` });
    severity = "bad"; label = "worst case"; refRow = "r6";
  } else {
    if (c < 30) {
      messages.push({ html:
        `<b>Underfitting (high bias).</b> The × sits far off the ` +
        `bullseye — every retraining misses the SAME way. Remedy: more ` +
        `features, more capacity, longer training, boosting.` });
      severity = "bad"; label = "underfit"; refRow = "r3";
    }
    if (gap > 0.05) {
      messages.push({ html:
        `<b>Overfitting (high variance).</b> The × stays near center ` +
        `but darts SCATTER — each retraining wrong in a different ` +
        `direction; spread = the live gap (${(100 * gap).toFixed(1)} ` +
        `pts). Remedy: regularization, bagging, more data, early ` +
        `stopping.` });
      severity = "bad"; label = "overfit"; refRow = "r4";
    }
  }
  if (p <= 0.12 && m.accuracy > 0.8
      && (m.recall < 0.6 || m.precision < 0.6)) {
    messages.push({ html:
      `<b>Imbalance trap.</b> Accuracy ${pctS(m.accuracy)} flatters — ` +
      `AUC-ROC ${inp.aucRoc.toFixed(3)} ignores imbalance while PR-AUC ` +
      `${inp.aucPr.toFixed(3)} exposes it (takeaway move 2). Remedy: ` +
      `judge by F1/PR-AUC, rebalance.` });
    if (!refRow) refRow = "r5";
    severity = "bad";
    if (label === "healthy") label = "imbalance trap";
  }
  if (refRow === null && severity !== "info") {
    if (m.precision < 0.7 && m.recall >= 0.7) {
      messages.push({ html:
        `<b>Low precision, healthy recall</b> → ${counts.FP} false ` +
        `alarms. Remedy: RAISE the threshold (takeaway move 3).` });
      severity = "bad"; label = "low precision"; refRow = "r1";
    } else if (m.recall < 0.7 && m.precision >= 0.7) {
      messages.push({ html:
        `<b>Low recall, healthy precision</b> → ${counts.FN} cases slip ` +
        `past. Remedy: LOWER the threshold (takeaway move 3).` });
      severity = "bad"; label = "low recall"; refRow = "r2";
    } else {
      messages.push({ html:
        `<b>Healthy.</b> Dots near their ★ corners, darts tight around ` +
        `a centered ×. Threshold is a business choice: which costs ` +
        `more, FP or FN?` });
      if (p <= 0.25) {
        messages.push({ info: true, html:
          `<b>Imbalance present but managed</b> ` +
          `(${Math.round(p * 100)}% positives): both metrics hold, ` +
          `rebalancing gains nothing. Watch PR-AUC as positives get ` +
          `rarer.` });
        label = "healthy · imbalance managed";
      }
      if (N <= 50 && bv.variance >= 0.2) {
        messages.push({ info: true, html:
          `<b>Small training set</b> (${N} cases): spread shows ` +
          `instability — small data raises variance, not bias; more ` +
          `data tightens it.` });
        if (label === "healthy") label = "healthy · small data";
      }
    }
  }
  return { severity, label, refRow, messages };
}
