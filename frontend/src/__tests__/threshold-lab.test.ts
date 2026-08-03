import { describe, it, expect } from "vitest";
import {
  casesToText, countsAt, metricsOf, parseCasesText, prCurve, rocCurve,
  type LabCase,
} from "@/lib/thresholdLab";

// Small hand-checkable dataset: 3 positives, 3 negatives.
const CASES: LabCase[] = [
  { score: 0.1, actual: 0 },
  { score: 0.3, actual: 0 },
  { score: 0.4, actual: 1 },
  { score: 0.6, actual: 0 },
  { score: 0.7, actual: 1 },
  { score: 0.9, actual: 1 },
];

describe("countsAt / metricsOf", () => {
  it("classifies at threshold 0.5 (score >= t is positive)", () => {
    const c = countsAt(CASES, 0.5);
    expect(c).toEqual({ TP: 2, FP: 1, FN: 1, TN: 2 });
    const m = metricsOf(c);
    expect(m.precision).toBeCloseTo(2 / 3);
    expect(m.recall).toBeCloseTo(2 / 3);
    expect(m.accuracy).toBeCloseTo(4 / 6);
    expect(m.f1).toBeCloseTo(2 / 3);
  });
  it("threshold 0 flags everything; threshold above max flags nothing", () => {
    expect(countsAt(CASES, 0)).toEqual({ TP: 3, FP: 3, FN: 0, TN: 0 });
    expect(countsAt(CASES, 0.95)).toEqual({ TP: 0, FP: 0, FN: 3, TN: 3 });
  });
  it("zero-division guards: no predicted positives → precision 0, f1 0", () => {
    const m = metricsOf({ TP: 0, FP: 0, FN: 3, TN: 3 });
    expect(m.precision).toBe(0);
    expect(m.f1).toBe(0);
  });
});

describe("rocCurve", () => {
  it("a perfectly separating model has AUC 1", () => {
    const perfect: LabCase[] = [
      { score: 0.1, actual: 0 }, { score: 0.2, actual: 0 },
      { score: 0.8, actual: 1 }, { score: 0.9, actual: 1 },
    ];
    expect(rocCurve(perfect).auc).toBeCloseTo(1);
  });
  it("an anti-model has AUC 0", () => {
    const inverted: LabCase[] = [
      { score: 0.9, actual: 0 }, { score: 0.8, actual: 0 },
      { score: 0.1, actual: 1 }, { score: 0.2, actual: 1 },
    ];
    expect(rocCurve(inverted).auc).toBeCloseTo(0);
  });
  it("single-class data yields no curve", () => {
    expect(rocCurve([{ score: 0.5, actual: 1 }]).points).toEqual([]);
  });
  it("curve endpoints span (0,0) to (1,1)", () => {
    const { points } = rocCurve(CASES);
    expect(points[0]).toEqual({ fpr: 0, tpr: 0 });
    expect(points[points.length - 1]).toEqual({ fpr: 1, tpr: 1 });
  });
});

describe("prCurve", () => {
  it("perfect model has AP 1 and prevalence = positive share", () => {
    const perfect: LabCase[] = [
      { score: 0.1, actual: 0 }, { score: 0.2, actual: 0 },
      { score: 0.8, actual: 1 }, { score: 0.9, actual: 1 },
    ];
    const { ap, prevalence } = prCurve(perfect);
    expect(ap).toBeCloseTo(1);
    expect(prevalence).toBeCloseTo(0.5);
  });
  it("AP of the demo set is between prevalence and 1", () => {
    const { ap, prevalence } = prCurve(CASES);
    expect(ap).toBeGreaterThan(prevalence);
    expect(ap).toBeLessThanOrEqual(1);
  });
});

describe("parseCasesText / casesToText", () => {
  it("parses valid lines, skips blanks and comments, flags bad lines", () => {
    const { cases, errors } = parseCasesText(
      "0.2, 0\n\n# comment\n0.9 , 1\nnot-a-line\n1.4, 1\n0.5, 2\n");
    expect(cases).toEqual([
      { score: 0.2, actual: 0 }, { score: 0.9, actual: 1 },
    ]);
    expect(errors.map((e) => e.line)).toEqual([5, 6, 7]);
  });
  it("round-trips", () => {
    const text = casesToText(CASES);
    expect(parseCasesText(text).cases).toEqual(CASES);
    expect(parseCasesText(text).errors).toEqual([]);
  });
});
