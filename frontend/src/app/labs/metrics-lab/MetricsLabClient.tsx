"use client";
/**
 * Classification Metrics Lab — interactive client.
 *
 * All simulation/diagnosis math lives in lib/modelErrorLab (unit
 * tested); this component owns only state, canvas drawing and layout.
 * The two teaching blocks (takeaway card, reference table) arrive as
 * SANITIZED admin HTML from the server component — already rendered in
 * the initial SSR payload for SEO, and reused here untouched.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  bandOf, biasVariance, curves, diagnose, metricsOf, rates, sample,
  seps, tally, type Counts, type Diagnosis, type LabSample,
} from "@/lib/modelErrorLab";

const NEG_FILL = "#85B7EB", NEG_EDGE = "#185FA5";
const POS_FILL = "#F0997B", POS_EDGE = "#993C1D";
const ERR_FILL = "#F7C1C1", ERR_EDGE = "#A32D2D";

const SCENARIOS: Record<string, {
  n: number; c: number; p: number; t: number; msg: string;
}> = {
  imbalance: { n: 500, c: 58, p: 5, t: 42,
    msg: "Accuracy high, precision collapses; PR-AUC drops, AUC-ROC barely moves." },
  overfit: { n: 200, c: 95, p: 30, t: 50,
    msg: "Darts SCATTER around a centered × — wrong differently each retraining." },
  underfit: { n: 200, c: 5, p: 30, t: 50,
    msg: "× drifts OFF-center — wrong the SAME way every retraining." },
  recall: { n: 100, c: 58, p: 30, t: 72,
    msg: "ROC dot far below its ★; circles pile up as misses." },
  worst: { n: 20, c: 5, p: 30, t: 50,
    msg: "Too simple AND too little data — × off-center AND scattered." },
  reset: { n: 500, c: 58, p: 30, t: 50,
    msg: "Baseline — darts tight around a centered ×. Break it yourself." },
};

function pct(x: number): string { return (100 * x).toFixed(1) + "%"; }

function setupCanvas(c: HTMLCanvasElement, h: number) {
  const dpr = window.devicePixelRatio || 1;
  const w = c.parentElement?.clientWidth ?? 300;
  c.width = w * dpr; c.height = h * dpr;
  c.style.width = `${w}px`; c.style.height = `${h}px`;
  // jsdom (vitest) has no canvas backend — getContext returns null.
  // Skip drawing there; all numbers/verdicts still render and assert.
  const g = c.getContext("2d");
  if (!g) return null;
  g.scale(dpr, dpr); g.clearRect(0, 0, w, h);
  return { g, w };
}

function drawStrip(c: HTMLCanvasElement, smp: LabSample, thr: number) {
  const h = 96;
  const ctx = setupCanvas(c, h);
  if (!ctx) return;
  const { g, w } = ctx;
  const X = (v: number) => v * w;
  const tx = X(thr);
  g.fillStyle = "rgba(24,95,165,0.05)"; g.fillRect(0, 0, tx, h - 12);
  g.fillStyle = "rgba(216,90,48,0.06)"; g.fillRect(tx, 0, w - tx, h - 12);
  const N = smp.pos.length + smp.neg.length;
  const r = N <= 50 ? 4.5 : N <= 100 ? 3.6 : N <= 200 ? 2.8 : 2.1;
  const rows = N <= 50 ? 2 : N <= 100 ? 3 : N <= 200 ? 4 : 6;
  const dy = N <= 100 ? 11 : N <= 200 ? 8 : 6;
  const paint = (list: LabSample["pos"], rowY: number) => {
    list.forEach((d, i) => {
      const x = X(d.score), y = rowY + (i % rows) * dy;
      const err = (d.score >= thr) !== d.isPos;
      if (d.isPos) {
        g.beginPath(); g.arc(x, y, r, 0, 7);
        g.fillStyle = err ? ERR_FILL : POS_FILL; g.fill();
        g.strokeStyle = err ? ERR_EDGE : POS_EDGE; g.lineWidth = 1.1;
        g.stroke();
      } else {
        g.fillStyle = err ? ERR_FILL : NEG_FILL;
        g.fillRect(x - r, y - r, 2 * r, 2 * r);
        g.strokeStyle = err ? ERR_EDGE : NEG_EDGE; g.lineWidth = 1.1;
        g.strokeRect(x - r, y - r, 2 * r, 2 * r);
      }
      if (err) {
        g.beginPath();
        g.moveTo(x - r - 2, y + r + 2); g.lineTo(x + r + 2, y - r - 2);
        g.strokeStyle = ERR_EDGE; g.lineWidth = 1.4; g.stroke();
      }
    });
  };
  paint(smp.neg, 10); paint(smp.pos, 10 + rows * dy + 9);
  g.setLineDash([4, 3]); g.beginPath();
  g.moveTo(tx, 0); g.lineTo(tx, h - 12);
  g.strokeStyle = "#444441"; g.lineWidth = 1.6; g.stroke();
  g.setLineDash([]);
  g.font = "10px sans-serif"; g.fillStyle = "#888780";
  g.fillText("0.0", 2, h - 2); g.fillText("1.0", w - 18, h - 2);
}

function drawCurve(c: HTMLCanvasElement,
                   pts: { x: number; y: number }[],
                   cur: { x: number; y: number },
                   base: "diag" | number,
                   ideal: [number, number]) {
  const h = 110;
  const ctx = setupCanvas(c, h);
  if (!ctx) return;
  const { g, w } = ctx;
  const L = 4;
  const X = (v: number) => L + v * (w - L - 4);
  const Y = (v: number) => 3 + (1 - v) * (h - 8);
  g.strokeStyle = "rgba(136,135,128,0.35)"; g.lineWidth = 1;
  g.strokeRect(L, 3, w - L - 4, h - 8);
  g.setLineDash([3, 3]); g.beginPath();
  if (base === "diag") { g.moveTo(X(0), Y(0)); g.lineTo(X(1), Y(1)); }
  else { g.moveTo(X(0), Y(base)); g.lineTo(X(1), Y(base)); }
  g.strokeStyle = "#B4B2A9"; g.stroke(); g.setLineDash([]);
  g.beginPath();
  pts.forEach((pt, i) => {
    if (i) g.lineTo(X(pt.x), Y(pt.y)); else g.moveTo(X(pt.x), Y(pt.y));
  });
  g.strokeStyle = "#534AB7"; g.lineWidth = 2; g.stroke();
  g.font = "12px sans-serif"; g.fillStyle = "#854F0B";
  g.fillText("★", X(ideal[0]) + (ideal[0] ? -11 : 3), Y(ideal[1]) + 10);
  g.beginPath(); g.arc(X(cur.x), Y(cur.y), 4.5, 0, 7);
  g.fillStyle = "#D85A30"; g.fill();
  g.strokeStyle = "#712B13"; g.lineWidth = 1.3; g.stroke();
}

function drawDart(c: HTMLCanvasElement, bias: number, variance: number) {
  const h = 110;
  const ctx = setupCanvas(c, h);
  if (!ctx) return;
  const { g, w } = ctx;
  const cx = w / 2, cy = h / 2, R = h / 2 - 4;
  const rings: [number, string][] = [
    [R, "#D3D1C7"], [R * 0.72, "#F1EFE8"],
    [R * 0.44, "#D3D1C7"], [R * 0.2, "#F1EFE8"],
  ];
  rings.forEach(([rr, col]) => {
    g.beginPath(); g.arc(cx, cy, rr, 0, 7); g.fillStyle = col; g.fill();
  });
  g.beginPath(); g.arc(cx, cy, R * 0.09, 0, 7);
  g.fillStyle = "#993C1D"; g.fill();
  const off = bias * R * 0.85, spread = 2 + variance * R * 0.8;
  const ox = cx - off * 0.75, oy = cy - off * 0.65;
  for (let i = 0; i < 8; i++) {
    const a = i * 2.399 + 0.7;
    const rad = ((i * 37) % 17) / 17 * spread;
    const dx = ox + Math.cos(a) * rad, dyy = oy + Math.sin(a) * rad;
    g.beginPath(); g.arc(dx, dyy, 2.1, 0, 7);
    g.fillStyle = "#26215C"; g.fill();
    g.strokeStyle = "#EEEDFE"; g.lineWidth = 0.7; g.stroke();
  }
  g.strokeStyle = "#A32D2D"; g.lineWidth = 1.6;
  g.beginPath();
  g.moveTo(ox - 4, oy); g.lineTo(ox + 4, oy);
  g.moveTo(ox, oy - 4); g.lineTo(ox, oy + 4);
  g.stroke();
}

function drawCM(c: HTMLCanvasElement, m: Counts) {
  const h = 160;
  const ctx = setupCanvas(c, h);
  if (!ctx) return;
  const { g, w } = ctx;
  const L = 60, T = 16, cw = (w - L - 4) / 2, ch = (h - T - 4) / 2;
  g.font = "10px sans-serif"; g.fillStyle = "#888780";
  g.fillText("actually +", L + cw / 2 - 24, 10);
  g.fillText("actually −", L + cw + cw / 2 - 24, 10);
  g.fillText("predicted +", 2, T + ch / 2);
  g.fillText("predicted −", 2, T + ch + ch / 2);
  const cells = [
    { n: m.TP, x: 0, y: 0, circ: true, err: false,
      bg: "rgba(29,158,117,0.08)" },
    { n: m.FP, x: 1, y: 0, circ: false, err: true,
      bg: "rgba(239,159,39,0.10)" },
    { n: m.FN, x: 0, y: 1, circ: true, err: true,
      bg: "rgba(163,45,45,0.07)" },
    { n: m.TN, x: 1, y: 1, circ: false, err: false,
      bg: "rgba(136,135,128,0.07)" },
  ];
  cells.forEach((cl) => {
    const x0 = L + cl.x * cw, y0 = T + cl.y * ch;
    g.fillStyle = cl.bg; g.fillRect(x0 + 1, y0 + 1, cw - 2, ch - 2);
    const show = Math.min(cl.n, 36);
    const cols = 9, r = 3, gap = 7;
    for (let i = 0; i < show; i++) {
      const gx = x0 + 9 + (i % cols) * gap;
      const gy = y0 + 11 + Math.floor(i / cols) * gap;
      if (cl.circ) {
        g.beginPath(); g.arc(gx, gy, r, 0, 7);
        g.fillStyle = cl.err ? ERR_FILL : POS_FILL; g.fill();
        g.strokeStyle = cl.err ? ERR_EDGE : POS_EDGE; g.lineWidth = 1;
        g.stroke();
      } else {
        g.fillStyle = cl.err ? ERR_FILL : NEG_FILL;
        g.fillRect(gx - r, gy - r, 2 * r, 2 * r);
        g.strokeStyle = cl.err ? ERR_EDGE : NEG_EDGE; g.lineWidth = 1;
        g.strokeRect(gx - r, gy - r, 2 * r, 2 * r);
      }
      if (cl.err) {
        g.beginPath();
        g.moveTo(gx - r - 1, gy + r + 1); g.lineTo(gx + r + 1, gy - r - 1);
        g.strokeStyle = ERR_EDGE; g.lineWidth = 1.1; g.stroke();
      }
    }
    g.fillStyle = "#444441";
    const extra = cl.n > show ? `${cl.n} total` : String(cl.n);
    g.fillText(extra, x0 + cw - g.measureText(extra).width - 5,
      y0 + ch - 5);
  });
}

const VERDICT_STYLE: Record<string, string> = {
  ok: "bg-emerald-50 text-emerald-700",
  info: "bg-indigo-50 text-indigo-700",
  bad: "bg-rose-50 text-rose-700",
};
const DIAG_STYLE: Record<string, string> = {
  ok: "bg-slate-50 text-slate-800",
  info: "bg-indigo-50 text-indigo-800",
  bad: "bg-rose-50 text-rose-800",
};

export function MetricsLabClient({
  takeawayHtml,
  referenceHtml,
}: {
  takeawayHtml: string;
  referenceHtml: string;
}) {
  const [n, setN] = useState(500);
  const [cx, setCx] = useState(58);
  const [prev, setPrev] = useState(30);
  const [thr, setThr] = useState(50);
  const [note, setNote] = useState(SCENARIOS.reset.msg);

  const strT = useRef<HTMLCanvasElement>(null);
  const strE = useRef<HTMLCanvasElement>(null);
  const rocRef = useRef<HTMLCanvasElement>(null);
  const prcRef = useRef<HTMLCanvasElement>(null);
  const dartRef = useRef<HTMLCanvasElement>(null);
  const cmRef = useRef<HTMLCanvasElement>(null);

  // ── derive everything from state (pure lib) ─────────────────────
  const p = prev / 100, t = thr / 100;
  const s = seps(cx);
  const smpTrain = sample(n, p, s.train);
  const smpTest = sample(n, p, s.test);
  const mTrain = tally(smpTrain, t);
  const m = tally(smpTest, t);
  const met = metricsOf(m);
  const metTrain = metricsOf(mTrain);
  const cv = curves(s.test, p);
  const cur = rates(s.test, t);
  const curPrec = p * cur.tpr + (1 - p) * cur.fpr > 1e-9
    ? (p * cur.tpr) / (p * cur.tpr + (1 - p) * cur.fpr) : 1;
  const bv = biasVariance(cx, n);
  const gap = metTrain.accuracy - met.accuracy;
  const diag: Diagnosis = diagnose({
    N: n, complexity: cx, prevalence: p, metrics: met, counts: m,
    trainAccuracy: metTrain.accuracy,
    aucRoc: cv.aucRoc, aucPr: cv.aucPr,
  });

  const redraw = useCallback(() => {
    if (strT.current) drawStrip(strT.current, smpTrain, t);
    if (strE.current) drawStrip(strE.current, smpTest, t);
    if (rocRef.current) drawCurve(rocRef.current, cv.roc,
      { x: cur.fpr, y: cur.tpr }, "diag", [0, 1]);
    if (prcRef.current) drawCurve(prcRef.current, cv.pr,
      { x: cur.tpr, y: curPrec }, p, [1, 1]);
    if (dartRef.current) drawDart(dartRef.current, bv.bias, bv.variance);
    if (cmRef.current) drawCM(cmRef.current, m);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [n, cx, prev, thr]);

  useEffect(() => {
    redraw();
    window.addEventListener("resize", redraw);
    return () => window.removeEventListener("resize", redraw);
  }, [redraw]);

  function applyScenario(key: keyof typeof SCENARIOS) {
    const sc = SCENARIOS[key];
    setN(sc.n); setCx(sc.c); setPrev(sc.p); setThr(sc.t);
    setNote(sc.msg);
  }

  const complexityLabel =
    cx < 30 ? "too simple" : cx > 72 ? "too complex" : "balanced";

  return (
    <div>
      {/* Verdict summary — sticky so it stays visible while dragging */}
      <div className="sticky top-0 z-10 bg-white/95 backdrop-blur
                      border border-slate-200 rounded-xl px-3 py-2 mb-3
                      flex flex-wrap gap-x-4 gap-y-1 items-center text-sm"
           data-testid="summary-bar">
        <span className={`font-semibold px-2.5 py-0.5 rounded-full text-xs
                          ${VERDICT_STYLE[diag.severity]}`}
              data-testid="verdict">
          {diag.label}
        </span>
        <span className="text-slate-500">P <b className="text-slate-900">{pct(met.precision)}</b></span>
        <span className="text-slate-500">R <b className="text-slate-900">{pct(met.recall)}</b></span>
        <span className="text-slate-500">Acc <b className="text-slate-900">{pct(met.accuracy)}</b></span>
        <span className="text-slate-500">
          Gap <b className={gap > 0.05 ? "text-rose-600" : "text-slate-900"}>
            {(100 * gap).toFixed(1)} pts</b>
        </span>
        <span className="text-slate-500">AUC-ROC <b className="text-slate-900">{cv.aucRoc.toFixed(3)}</b></span>
        <span className="text-slate-500">PR-AUC <b className="text-slate-900">{cv.aucPr.toFixed(3)}</b></span>
      </div>

      {/* Scenario buttons */}
      <div className="flex flex-wrap gap-2 mb-2">
        {([
          ["imbalance", "1 · Imbalance trap"],
          ["overfit", "2 · Overfitting"],
          ["underfit", "3 · Underfitting"],
          ["recall", "4 · Bad recall"],
          ["worst", "5 · Worst case"],
          ["reset", "Reset"],
        ] as const).map(([key, label]) => (
          <button key={key}
                  onClick={() => applyScenario(key)}
                  className="text-xs px-3 py-1.5 border border-slate-300
                             rounded-lg hover:bg-slate-50 hover:border-indigo-300">
            {label}
          </button>
        ))}
      </div>
      {note && (
        <p className="text-xs text-indigo-600 mb-3" data-testid="scenario-note">
          {note}
        </p>
      )}

      {/* Controls */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-3">
        <label className="block text-xs text-slate-600">
          <span className="flex justify-between">
            Cases per set <b className="text-slate-900">{n}</b>
          </span>
          <select value={n} onChange={(e) => { setN(+e.target.value); setNote(""); }}
                  className="w-full mt-1 px-2 py-1.5 border border-slate-300
                             rounded text-sm">
            {[20, 50, 100, 200, 500].map((v) =>
              <option key={v} value={v}>{v}</option>)}
          </select>
          <span className="block text-[10px] text-slate-400 mt-0.5">
            small data → unstable model (adds variance, not bias)
          </span>
        </label>
        <label className="block text-xs text-slate-600">
          <span className="flex justify-between">
            Model complexity <b className="text-slate-900">{complexityLabel}</b>
          </span>
          <input type="range" min={0} max={100} value={cx}
                 onChange={(e) => { setCx(+e.target.value); setNote(""); }}
                 className="w-full mt-2" aria-label="Model complexity" />
          <span className="flex justify-between text-[10px] text-slate-400">
            <span>too simple</span><span>too complex</span>
          </span>
        </label>
        <label className="block text-xs text-slate-600">
          <span className="flex justify-between">
            Positive share <b className="text-slate-900">{prev}%</b>
          </span>
          <input type="range" min={2} max={50} value={prev}
                 onChange={(e) => { setPrev(+e.target.value); setNote(""); }}
                 className="w-full mt-2" aria-label="Positive class share" />
          <span className="flex justify-between text-[10px] text-slate-400">
            <span>rare</span><span>balanced</span>
          </span>
        </label>
        <label className="block text-xs text-slate-600">
          <span className="flex justify-between">
            Decision threshold <b className="text-slate-900">{t.toFixed(2)}</b>
          </span>
          <input type="range" min={0} max={100} value={thr}
                 onChange={(e) => { setThr(+e.target.value); setNote(""); }}
                 className="w-full mt-2" aria-label="Decision threshold" />
          <span className="flex justify-between text-[10px] text-slate-400">
            <span>0 — all flagged positive</span><span>1 — none</span>
          </span>
        </label>
      </div>

      {/* Diagnosis — directly under the controls, updates in view */}
      <div className={`rounded-xl px-4 py-3 mb-4 text-sm leading-relaxed
                       ${DIAG_STYLE[diag.severity]}`}
           data-testid="diagnosis">
        {diag.messages.map((msg, i) => (
          <p key={i} className={i ? "mt-2" : ""}
             dangerouslySetInnerHTML={{ __html: msg.html }} />
        ))}
      </div>

      {/* Strips */}
      <div className="border border-slate-200 rounded-xl px-3 pt-2 pb-1 mb-2">
        <div className="flex justify-between text-xs mb-1">
          <span className="font-medium text-slate-800">
            1 · Training set (memorized)
          </span>
          <span className="text-slate-500">
            acc <b className="text-slate-900">{pct(metTrain.accuracy)}</b>
          </span>
        </div>
        <div className="relative h-24"><canvas ref={strT} /></div>
      </div>
      <div className="border border-slate-200 rounded-xl px-3 pt-2 pb-1 mb-4">
        <div className="flex justify-between text-xs mb-1">
          <span className="font-medium text-slate-800">
            2 · Held-out test set (all metrics use this)
          </span>
          <span className="text-slate-500">
            acc <b className="text-slate-900">{pct(met.accuracy)}</b>
          </span>
        </div>
        <div className="relative h-24"><canvas ref={strE} /></div>
      </div>
      <p className="text-xs text-slate-500 -mt-2 mb-4">
        <span className="inline-block w-2.5 h-2.5 rounded-full align-[-1px]"
              style={{ background: POS_FILL, border: `1.5px solid ${POS_EDGE}` }} />{" "}
        actually positive ·{" "}
        <span className="inline-block w-2.5 h-2.5 align-[-1px]"
              style={{ background: NEG_FILL, border: `1.5px solid ${NEG_EDGE}` }} />{" "}
        actually negative ·{" "}
        <span className="text-rose-700 font-medium">red slash = misclassified</span>
      </p>

      {/* Curves + dartboard */}
      <div className="grid sm:grid-cols-3 gap-3 mb-4">
        <div className="border border-slate-200 rounded-xl p-2">
          <div className="text-xs text-slate-500 mb-1">
            ROC · AUC <b className="text-indigo-700">{cv.aucRoc.toFixed(3)}</b>
          </div>
          <div className="relative h-[110px]"><canvas ref={rocRef} /></div>
          <div className="text-[10px] text-slate-400 mt-1">
            y = recall · x = false-positive rate · closer to ★ (top-left) = better
          </div>
        </div>
        <div className="border border-slate-200 rounded-xl p-2">
          <div className="text-xs text-slate-500 mb-1">
            PR · AUC <b className="text-indigo-700">{cv.aucPr.toFixed(3)}</b>
          </div>
          <div className="relative h-[110px]"><canvas ref={prcRef} /></div>
          <div className="text-[10px] text-slate-400 mt-1">
            y = precision · x = recall · closer to ★ (top-right) = better
          </div>
        </div>
        <div className="border border-slate-200 rounded-xl p-2">
          <div className="text-xs text-slate-500 mb-1">
            Bias–variance target ·{" "}
            <b className="text-slate-900" data-testid="bvlabel">
              bias {bandOf(bv.bias, 0.3, 0.6)} · variance{" "}
              {bandOf(bv.variance, 0.2, 0.6)}
            </b>
          </div>
          <div className="relative h-[110px]"><canvas ref={dartRef} /></div>
          <div className="text-[10px] text-slate-400 mt-1">
            × = cluster average. bias = where × sits · variance = spread
            around ×
          </div>
        </div>
      </div>

      {/* Takeaway — admin-editable HTML (sanitized server-side) */}
      <section className="border border-slate-200 rounded-xl px-4 py-3 mb-4
                          bg-slate-50">
        <h2 className="text-sm font-semibold text-slate-900 mb-1.5">
          How to use the AUC curves — three moves
        </h2>
        <div className="text-sm leading-relaxed text-slate-700
                        [&_table]:w-full [&_td]:py-0.5"
             dangerouslySetInnerHTML={{ __html: takeawayHtml }} />
      </section>

      {/* Matrix pictures + formulas */}
      <div className="grid md:grid-cols-2 gap-3 mb-4">
        <div className="border border-slate-200 rounded-xl p-3">
          <div className="text-xs text-slate-500 mb-1">
            Confusion matrix as pictures — predicted on rows, actual on
            columns
          </div>
          <div className="relative h-40"><canvas ref={cmRef} /></div>
          <div className="grid grid-cols-2 gap-1.5 text-xs mt-2">
            <div className="bg-emerald-50 rounded px-2 py-1 text-emerald-700">
              TP caught <b data-testid="tp">{m.TP}</b>
            </div>
            <div className="bg-amber-50 rounded px-2 py-1 text-amber-700">
              FP false alarm <b data-testid="fp">{m.FP}</b>
            </div>
            <div className="bg-rose-50 rounded px-2 py-1 text-rose-700">
              FN missed <b data-testid="fn">{m.FN}</b>
            </div>
            <div className="bg-slate-100 rounded px-2 py-1 text-slate-600">
              TN cleared <b data-testid="tn">{m.TN}</b>
            </div>
          </div>
        </div>
        <div className="border border-slate-200 rounded-xl p-3 text-xs">
          <div className="text-slate-500 mb-2">
            Metrics — formula · your numbers · what it asks
          </div>
          <div className="font-mono text-[11.5px] text-slate-900">
            <b>Precision</b> = TP/(TP+FP) = {m.TP}/({m.TP}+{m.FP}) ={" "}
            {pct(met.precision)}
          </div>
          <p className="text-[10.5px] text-slate-400 mb-1.5">
            of everything the model FLAGGED, how much was real? (reads
            ACROSS the predicted+ row)
          </p>
          <div className="font-mono text-[11.5px] text-slate-900">
            <b>Recall</b> = TP/(TP+FN) = {m.TP}/({m.TP}+{m.FN}) ={" "}
            {pct(met.recall)}
          </div>
          <p className="text-[10.5px] text-slate-400 mb-1.5">
            of everything actually POSITIVE, how much did we catch?
            (reads DOWN the actually+ column)
          </p>
          <div className="font-mono text-[11.5px] text-slate-900">
            <b>F1</b> = 2·P·R/(P+R) = {pct(met.f1)}
          </div>
          <p className="text-[10.5px] text-slate-400 mb-1.5">
            one number combining both — high only when BOTH are decent
          </p>
          <div className="font-mono text-[11.5px] text-slate-900">
            <b>Accuracy</b> = (TP+TN)/all = ({m.TP}+{m.TN})/{n} ={" "}
            {pct(met.accuracy)}
          </div>
          <p className="text-[10.5px] text-slate-400 mb-1.5">
            share of ALL cases correct — flattering when one class
            dominates
          </p>
          <div className="font-mono text-[11.5px] text-slate-900">
            <b>Gap</b> = acc(train) − acc(test) = {pct(metTrain.accuracy)}{" "}
            − {pct(met.accuracy)} ={" "}
            <span className={gap > 0.05 ? "text-rose-600" : ""}>
              {(100 * gap).toFixed(1)} pts
            </span>
          </div>
          <p className="text-[10.5px] text-slate-400">
            how much better on memorized data than new — the overfitting
            detector
          </p>
        </div>
      </div>

      {/* Reference — admin-editable HTML (sanitized server-side) */}
      <section className="border border-slate-200 rounded-xl px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-900 mb-1.5">
          Reference — cause · consequence · remedy
        </h2>
        <div className="text-xs leading-relaxed text-slate-700 overflow-x-auto
                        [&_table]:w-full [&_table]:min-w-[520px]
                        [&_th]:text-left [&_th]:font-medium [&_th]:text-slate-500
                        [&_th]:py-1 [&_th]:pr-3 [&_td]:py-1.5 [&_td]:pr-3
                        [&_tr]:border-t [&_tr]:border-slate-100"
             dangerouslySetInnerHTML={{ __html: referenceHtml }} />
      </section>
    </div>
  );
}
