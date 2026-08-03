"use client";
/**
 * Interactive Threshold Explorer (port of the standalone HTML page).
 *
 * Dataset comes from the admin-managed config (content.thresholdLab()).
 * All classification math lives in lib/thresholdLab (unit-tested); this
 * component only renders.
 *
 * Colour-vision accessibility (deliberate, per site owner):
 *  - correct  = light mint fill + SOLID teal outline, plain marker
 *  - error    = deep red fill + solid dark outline + one BOLD SLASH
 *    through the marker. Outlines are never dashed — dashes blur the
 *    circle-vs-square silhouette at small sizes. Nothing relies on hue
 *    alone.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { content as contentApi } from "@/lib/api";
import type { ThresholdExplorerConfig } from "@/types/api";
import {
  countsAt, metricsOf, prCurve, rocCurve, type LabCase,
} from "@/lib/thresholdLab";

// Palette (approved mock v2 + owner's colour picks)
const OK_FILL = "#A9E6CB", OK_LINE = "#0F766E";
const ER_FILL = "#E0544B", ER_LINE = "#7F1D1D";

// Strip geometry (matches the original page)
const X0 = 60, XW = 580;
const sx = (s: number) => X0 + s * XW;
// Curve geometry
const cx = (f: number) => 55 + f * 250;
const cy = (t: number) => 275 - t * 250;

const LANES_P = [52, 76, 100, 124, 148, 172];
const LANES_N = [64, 88, 112, 136, 160, 184];

function pct(v: number) { return `${Math.round(v * 100)}%`; }

export function ThresholdExplorerClient() {
  const [cfg, setCfg] = useState<ThresholdExplorerConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [t, setT] = useState(0.5);

  useEffect(() => {
    contentApi.thresholdLab()
      .then((c) => {
        setCfg(c);
        setT(Math.min(0.99, Math.max(0.01, c.threshold)));
      })
      .catch(() => setError("The lab's dataset could not be loaded. Please try again later."));
  }, []);

  const cases: LabCase[] = useMemo(
    () => (cfg?.mode === "cases" ? cfg.cases : []), [cfg]);
  const counts = useMemo(
    () => (cfg?.mode === "counts"
      ? { TP: cfg.tp, FP: cfg.fp, FN: cfg.fn, TN: cfg.tn }
      : countsAt(cases, t)),
    [cfg, cases, t]);
  const m = useMemo(() => metricsOf(counts), [counts]);
  const roc = useMemo(() => rocCurve(cases), [cases]);
  const pr = useMemo(() => prCurve(cases), [cases]);

  if (error) {
    return <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-xl text-sm">{error}</div>;
  }
  if (!cfg) {
    return <div className="text-slate-500 py-10 text-center">Loading the lab…</div>;
  }

  const interactive = cfg.mode === "cases" && cases.length > 0;
  const hasCurves = interactive && roc.points.length > 0;
  const NP = cases.filter((c) => c.actual === 1).length;
  const NN = cases.length - NP;
  const tpr = NP ? counts.TP / NP : 0;
  const fpr = NN ? counts.FP / NN : 0;
  const precNow = counts.TP + counts.FP ? counts.TP / (counts.TP + counts.FP) : 1;

  const posture = t <= 0.25
    ? <><b>Screening posture.</b> The line sits far left, so almost everything is flagged. Recall is high — you miss very little — but precision drops as false alarms pile up.</>
    : t >= 0.75
      ? <><b>Alarm posture.</b> The line sits far right, so the model only fires when very confident. Precision is high, but recall falls and real cases slip through.</>
      : <><b>Balanced posture.</b> Neither error is strongly favoured — F1 tends to peak somewhere in this middle band.</>;

  let ip = 0, inn = 0;

  return (
    <div className="space-y-5">
      {interactive && (
        <section className="bg-white border border-slate-200 rounded-2xl p-5">
          <h2 className="font-semibold text-slate-900 mb-1">Every case, one line</h2>
          <p className="text-xs text-slate-500 mb-3">
            ● circles = actually positive · ■ squares = actually negative.
            Plain marker = classified correctly · <b>bold slash = error</b>.
          </p>
          <svg viewBox="0 0 700 240" className="w-full h-auto" role="img"
               aria-label="Cases plotted by model score with a movable threshold">
            <rect x={X0} y={30} width={Math.max(0, sx(t) - X0)} height={170}
                  rx={8} fill={ER_FILL} opacity={0.05} />
            <rect x={sx(t)} y={30} width={Math.max(0, X0 + XW - sx(t))} height={170}
                  rx={8} fill={OK_FILL} opacity={0.16} />
            <text x={(X0 + sx(t)) / 2} y={22} fontSize={12} fill="#64748B"
                  textAnchor="middle">Predicted negative</text>
            <text x={(sx(t) + X0 + XW) / 2} y={22} fontSize={12} fill="#64748B"
                  textAnchor="middle">Predicted positive</text>
            <line x1={sx(t)} y1={30} x2={sx(t)} y2={200}
                  stroke="#475569" strokeWidth={1.6} strokeDasharray="5 3" />
            {cases.map((c, i) => {
              const predictedPos = c.score >= t;
              const ok = c.actual === 1 ? predictedPos : !predictedPos;
              const fill = ok ? OK_FILL : ER_FILL;
              const line = ok ? OK_LINE : ER_LINE;
              let lane: number;
              if (c.actual === 1) { lane = LANES_P[ip % LANES_P.length]; ip++; }
              else { lane = LANES_N[inn % LANES_N.length]; inn++; }
              const x = sx(c.score);
              return (
                <g key={i}>
                  {c.actual === 1
                    ? <circle cx={x} cy={lane} r={9} fill={fill} stroke={line} strokeWidth={2.5} />
                    : <rect x={x - 8} y={lane - 8} width={16} height={16} rx={2}
                            fill={fill} stroke={line} strokeWidth={2.5} />}
                  {!ok && (
                    <line x1={x - 11} y1={lane + 11} x2={x + 11} y2={lane - 11}
                          stroke={ER_LINE} strokeWidth={3.2} strokeLinecap="round" />
                  )}
                </g>
              );
            })}
            <line x1={X0} y1={206} x2={X0 + XW} y2={206} stroke="#E2E8F0" />
            <text x={X0} y={228} fontSize={12} fill="#94A3B8">Model score 0.0</text>
            <text x={X0 + XW} y={228} fontSize={12} fill="#94A3B8" textAnchor="end">1.0</text>
          </svg>
          <div className="flex items-center gap-4 mt-3">
            <label htmlFor="lab-th" className="text-sm font-semibold whitespace-nowrap">
              Threshold
            </label>
            <input id="lab-th" type="range" min={1} max={99} value={Math.round(t * 100)}
                   onChange={(e) => setT(Number(e.target.value) / 100)}
                   className="flex-1 accent-indigo-600 cursor-pointer" />
            <span className="text-indigo-700 font-bold tabular-nums w-12 text-right">
              {t.toFixed(2)}
            </span>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 mt-3 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-4 h-4 rounded-full border-[2.5px]"
                    style={{ background: OK_FILL, borderColor: OK_LINE }} />
              correct — plain marker
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-4 h-4 rounded-full border-[2.5px]"
                    style={{
                      borderColor: ER_LINE,
                      background: `linear-gradient(135deg, transparent 40%, ${ER_LINE} 40%, ${ER_LINE} 60%, transparent 60%), ${ER_FILL}`,
                    }} />
              error — bold slash through it
            </span>
          </div>
        </section>
      )}

      <section className="bg-white border border-slate-200 rounded-2xl p-5">
        <h2 className="font-semibold text-slate-900 mb-1">Confusion matrix &amp; metrics</h2>
        <p className="text-xs text-slate-500 mb-3">
          Error cells carry a heavier border and ✕ prefix — never colour alone.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          <MatrixCell ok label="✓ TP caught" value={counts.TP} />
          <MatrixCell label="✕ FP false alarm" value={counts.FP} />
          <MatrixCell label="✕ FN missed" value={counts.FN} />
          <MatrixCell ok label="✓ TN rejected" value={counts.TN} />
        </div>
        <div className="mt-4 space-y-2">
          <MetricBar name="Precision" v={m.precision} />
          <MetricBar name="Recall" v={m.recall} />
          <MetricBar name="Accuracy" v={m.accuracy} />
          <MetricBar name="F1" v={m.f1} />
        </div>
        <div className="mt-4 text-[13px] rounded-xl px-4 py-3 bg-indigo-50 border border-indigo-100 text-indigo-900">
          {cfg.mode === "counts"
            ? <><b>Snapshot mode.</b> Showing the fixed counts configured by the site admin — there are no per-case scores to re-threshold, so the slider and curves are hidden.</>
            : <>{posture}{counts.FN === 0 && <> You are currently missing <b>zero</b> real positives.</>}{counts.FP === 0 && <> You currently have <b>zero</b> false alarms.</>}</>}
        </div>
      </section>

      {hasCurves && (
        <section className="bg-white border border-slate-200 rounded-2xl p-5">
          <h2 className="font-semibold text-slate-900 mb-1">
            Two views of the same model — ROC and Precision–Recall
          </h2>
          <p className="text-xs text-slate-500 mb-4">
            Each point on a curve is one possible threshold. Sliding the control
            moves the dot along both curves at once — the curves themselves
            never change.
          </p>
          <div className="grid sm:grid-cols-2 gap-4">
            <CurveBox
              label="ROC-AUC · TPR vs FPR" auc={roc.auc} color="#1D4ED8"
              path={roc.points.map((p, i) =>
                `${i ? "L" : "M"}${cx(p.fpr).toFixed(1)} ${cy(p.tpr).toFixed(1)}`).join(" ")}
              dot={{ x: cx(fpr), y: cy(tpr) }}
              xLabel="False positive rate →" yLabel="True positive rate →"
              diagonal
            />
            <CurveBox
              label="PR-AUC · Precision vs Recall" auc={pr.ap} color="#B45309"
              path={pr.points.map((p, i) =>
                `${i ? "L" : "M"}${cx(p.rec).toFixed(1)} ${cy(p.prec).toFixed(1)}`).join(" ")}
              dot={{ x: cx(tpr), y: cy(precNow) }}
              xLabel="Recall →" yLabel="Precision →"
              baseline={pr.prevalence}
            />
          </div>
          <div className="mt-4 text-[13px] rounded-xl px-4 py-3 bg-blue-50 border border-blue-100 text-blue-900">
            <b>Why two curves?</b> On balanced data they tell a similar story. On
            imbalanced data ROC can look flatteringly high because the huge pool
            of true negatives keeps the false-positive rate low — the PR curve,
            which ignores true negatives entirely, stays honest.{" "}
            <b>When positives are rare, trust PR-AUC.</b> The PR baseline is the
            prevalence ({pct(pr.prevalence)} here) — beat that and the model adds value.
          </div>
          <table className="w-full text-sm mt-4">
            <tbody>
              <Row k="True positive rate (recall)" v={tpr.toFixed(3)} />
              <Row k="False positive rate" v={fpr.toFixed(3)} />
              <Row k="Precision" v={precNow.toFixed(3)} />
            </tbody>
          </table>
        </section>
      )}

      <section className="rounded-2xl p-5 bg-indigo-50 border border-indigo-100">
        <h2 className="font-semibold text-indigo-900 mb-1">Keep practicing</h2>
        <p className="text-sm text-indigo-900/80">
          This is exactly how the exam tests Domain IV — scenarios, not
          formulas.{" "}
          <Link href="/exams" className="font-semibold underline">
            Try the mock exams →
          </Link>
        </p>
      </section>
    </div>
  );
}

function MatrixCell({ ok = false, label, value }: {
  ok?: boolean; label: string; value: number;
}) {
  return (
    <div className={`rounded-xl px-2 py-3 text-center border-2 ${
      ok ? "bg-emerald-50 border-emerald-200" : "bg-rose-50 border-rose-800/60"
    }`}>
      <div className={`text-xs font-bold ${ok ? "text-emerald-800" : "text-rose-900"}`}>
        {label}
      </div>
      <div className={`text-2xl font-extrabold tabular-nums ${
        ok ? "text-emerald-900" : "text-rose-900"
      }`}>
        {value}
      </div>
    </div>
  );
}

function MetricBar({ name, v }: { name: string; v: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-20 text-sm text-slate-600">{name}</span>
      <div className="flex-1 h-2.5 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full bg-indigo-600 rounded-full transition-[width] duration-100"
             style={{ width: `${v * 100}%` }} />
      </div>
      <span className="w-11 text-right text-sm font-bold tabular-nums">{pct(v)}</span>
    </div>
  );
}

function CurveBox({ label, auc, color, path, dot, xLabel, yLabel, diagonal, baseline }: {
  label: string; auc: number; color: string; path: string;
  dot: { x: number; y: number }; xLabel: string; yLabel: string;
  diagonal?: boolean; baseline?: number;
}) {
  return (
    <div className="text-center">
      <svg viewBox="0 0 330 330" className="w-full max-w-[300px] h-auto mx-auto" role="img"
           aria-label={label}>
        <rect x={55} y={25} width={250} height={250} fill="#fff" stroke="#E2E8F0" />
        {diagonal && (
          <line x1={55} y1={275} x2={305} y2={25}
                stroke="#CBD5E1" strokeDasharray="4 4" />
        )}
        {baseline !== undefined && (
          <line x1={55} y1={cy(baseline)} x2={305} y2={cy(baseline)}
                stroke="#CBD5E1" strokeDasharray="4 4" />
        )}
        <path d={`${path} L305 275 L55 275 Z`} fill={color} opacity={0.18} />
        <path d={path} fill="none" stroke={color} strokeWidth={2.4}
              strokeLinejoin="round" />
        <circle cx={dot.x} cy={dot.y} r={6} fill="#4F46E5" stroke="#fff" strokeWidth={2} />
        <text x={180} y={305} fontSize={12} fill="#475569" textAnchor="middle">{xLabel}</text>
        <text x={18} y={150} fontSize={12} fill="#475569" textAnchor="middle"
              transform="rotate(-90 18 150)">{yLabel}</text>
      </svg>
      <div className="mt-1">
        <span className="text-2xl font-extrabold tabular-nums" style={{ color }}>
          {auc.toFixed(3)}
        </span>
        <div className="text-xs text-slate-500">{label}</div>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <tr className="border-b border-slate-100">
      <td className="py-1.5 text-slate-600">{k}</td>
      <td className="py-1.5 text-right tabular-nums font-medium">{v}</td>
    </tr>
  );
}
