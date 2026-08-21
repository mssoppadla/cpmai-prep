/**
 * Model Error Lab — simulation math, the diagnosis brain, the HTML
 * sanitizer, and the client component's scenario wiring.
 */
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  biasVariance, curves, diagnose, metricsOf, sample, seps,
  smallNVariance, tally,
} from "@/lib/modelErrorLab";
import { sanitizeHtml } from "@/lib/sanitizeHtml";
import { MetricsLabClient } from
  "@/app/labs/metrics-lab/MetricsLabClient";

function state(N: number, c: number, p: number, t: number) {
  const s = seps(c);
  const m = tally(sample(N, p, s.test), t);
  const mt = tally(sample(N, p, s.train), t);
  const met = metricsOf(m);
  const cv = curves(s.test, p);
  return diagnose({
    N, complexity: c, prevalence: p, metrics: met, counts: m,
    trainAccuracy: metricsOf(mt).accuracy,
    aucRoc: cv.aucRoc, aucPr: cv.aucPr,
  });
}

describe("modelErrorLab math", () => {
  it("matrix counts always sum to N and match the sampled dots", () => {
    const s = seps(58);
    const smp = sample(200, 0.3, s.test);
    const m = tally(smp, 0.5);
    expect(m.TP + m.FN).toBe(smp.pos.length);
    expect(m.FP + m.TN).toBe(smp.neg.length);
    expect(m.TP + m.FN + m.FP + m.TN).toBe(200);
  });

  it("threshold extremes: 0 flags everything, 1 flags nothing", () => {
    const s = seps(58);
    const smp = sample(100, 0.3, s.test);
    const all = tally(smp, 0);
    expect(all.FN).toBe(0);
    expect(all.TN).toBe(0);
    const none = tally(smp, 1);
    expect(none.TP).toBe(0);
    expect(none.FP).toBe(0);
  });

  it("overfit complexity opens the train-test gap; balanced does not", () => {
    expect(seps(58).gap).toBe(0);
    expect(seps(95).gap).toBeGreaterThan(0.3);
  });

  it("AUC degrades with underfitting and ignores the threshold", () => {
    const good = curves(seps(58).test, 0.3);
    const bad = curves(seps(5).test, 0.3);
    expect(good.aucRoc).toBeGreaterThan(0.9);
    expect(bad.aucRoc).toBeLessThan(0.8);
    expect(bad.aucRoc).toBeLessThan(good.aucRoc - 0.15);
    // curves() takes no threshold at all — API-level guarantee.
  });

  it("imbalance hits PR-AUC harder than AUC-ROC", () => {
    const sep = seps(58).test;
    const balanced = curves(sep, 0.5);
    const rare = curves(sep, 0.05);
    expect(Math.abs(balanced.aucRoc - rare.aucRoc)).toBeLessThan(0.01);
    expect(balanced.aucPr - rare.aucPr).toBeGreaterThan(0.08);
  });

  it("sample size moves variance only — bias is untouched", () => {
    const big = biasVariance(58, 500);
    const small = biasVariance(58, 20);
    expect(small.bias).toBe(big.bias);
    expect(small.variance).toBeGreaterThan(big.variance);
    expect(smallNVariance(20)).toBeGreaterThan(smallNVariance(500));
  });

  it("balanced baseline reads low bias and low variance", () => {
    const bv = biasVariance(58, 500);
    expect(bv.bias).toBeLessThan(0.3);
    expect(bv.variance).toBeLessThan(0.2);
  });
});

describe("diagnose — the five scenarios land on their verdicts", () => {
  it("underfitting", () => {
    const d = state(200, 5, 0.3, 0.5);
    expect(d.label).toBe("underfit");
    expect(d.refRow).toBe("r3");
    expect(d.messages[0].html).toContain("Underfitting");
  });
  it("overfitting", () => {
    const d = state(200, 95, 0.3, 0.5);
    expect(d.label).toBe("overfit");
    expect(d.refRow).toBe("r4");
  });
  it("imbalance trap", () => {
    const d = state(500, 58, 0.05, 0.42);
    expect(d.label).toBe("imbalance trap");
    expect(d.refRow).toBe("r5");
    expect(d.messages.map((m) => m.html).join(" ")).toContain("PR-AUC");
  });
  it("bad recall", () => {
    const d = state(100, 58, 0.3, 0.72);
    expect(d.label).toBe("low recall");
    expect(d.refRow).toBe("r2");
    expect(d.messages[0].html).toContain("LOWER the threshold");
  });
  it("worst case — both high", () => {
    const d = state(20, 5, 0.3, 0.5);
    expect(d.label).toBe("worst case");
    expect(d.refRow).toBe("r6");
    expect(d.messages.map((m) => m.html).join(" "))
      .toContain("more data first");
  });
  it("healthy baseline, with managed-imbalance info note when mild", () => {
    const d = state(500, 58, 0.3, 0.5);
    expect(d.severity).toBe("ok");
    const d2 = state(500, 58, 0.2, 0.5);
    expect(d2.severity).toBe("ok");
    expect(d2.label).toContain("imbalance managed");
  });
});

describe("sanitizeHtml", () => {
  it("keeps the allowed formatting vocabulary", () => {
    const html = '<b>Bold</b> <span style="color:#b91c1c">red</span>' +
      "<table><tr><td>cell</td></tr></table><br><ul><li>item</li></ul>";
    const out = sanitizeHtml(html);
    expect(out).toContain("<b>Bold</b>");
    expect(out).toContain('style="color: #b91c1c"');
    expect(out).toContain("<td>cell</td>");
    expect(out).toContain("<li>item</li>");
  });
  it("strips scripts, handlers and unsafe urls", () => {
    const out = sanitizeHtml(
      '<script>alert(1)</script><b onclick="x()">hi</b>' +
      '<a href="javascript:evil()">link</a>' +
      '<span style="background:url(x)">s</span><iframe src="x"></iframe>');
    expect(out).not.toContain("script");
    expect(out).not.toContain("onclick");
    expect(out).not.toContain("javascript:");
    expect(out).not.toContain("iframe");
    expect(out).toContain("<b>hi</b>");
    expect(out).toContain("link");      // text kept, href dropped
  });
  it("safe links gain rel/target", () => {
    const out = sanitizeHtml('<a href="https://cpmaiexamprep.com/x">go</a>');
    expect(out).toContain('rel="noopener noreferrer"');
    expect(out).toContain('href="https://cpmaiexamprep.com/x"');
  });
});

describe("MetricsLabClient", () => {
  const props = {
    takeawayHtml: "<b>Move 1</b> compare models by AUC.",
    referenceHtml: "<table><tbody><tr><td>Both low</td><td>Underfit</td>" +
      "</tr></tbody></table>",
  };

  it("renders healthy baseline with admin copy and formulas", () => {
    render(<MetricsLabClient {...props} />);
    expect(screen.getByTestId("verdict").textContent).toBe("healthy");
    expect(screen.getByText("Move 1")).toBeInTheDocument();
    expect(screen.getByText("Underfit")).toBeInTheDocument();
    expect(screen.getByTestId("diagnosis")).toBeInTheDocument();
    // Worked formula visible with substituted numbers
    expect(document.body.textContent).toContain("TP/(TP+FP)");
  });

  it("scenario buttons drive the verdict and the diagnosis", () => {
    render(<MetricsLabClient {...props} />);
    fireEvent.click(screen.getByText("3 · Underfitting"));
    expect(screen.getByTestId("verdict").textContent).toBe("underfit");
    expect(screen.getByTestId("diagnosis").textContent)
      .toContain("boosting");
    fireEvent.click(screen.getByText("2 · Overfitting"));
    expect(screen.getByTestId("verdict").textContent).toBe("overfit");
    expect(screen.getByTestId("bvlabel").textContent)
      .toContain("variance HIGH");
    fireEvent.click(screen.getByText("Reset"));
    expect(screen.getByTestId("verdict").textContent).toBe("healthy");
  });

  it("matrix numbers reconcile with the chosen sample size", () => {
    render(<MetricsLabClient {...props} />);
    fireEvent.click(screen.getByText("5 · Worst case"));   // N = 20
    const total =
      Number(screen.getByTestId("tp").textContent) +
      Number(screen.getByTestId("fn").textContent) +
      Number(screen.getByTestId("fp").textContent) +
      Number(screen.getByTestId("tn").textContent);
    expect(total).toBe(20);
  });
});
