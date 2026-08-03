"use client";
/**
 * Admin config for the public Threshold Explorer lab
 * (/labs/threshold-explorer). Replaces the old threshold_config.txt:
 * saved values live in system settings and go live on the public
 * page's next load.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { admin, errMsg } from "@/lib/api";
import type { ThresholdExplorerConfig } from "@/types/api";
import { casesToText, parseCasesText } from "@/lib/thresholdLab";

const input = "w-full px-3 py-2 text-sm border border-slate-300 rounded-lg " +
  "focus:outline-none focus:ring-2 focus:ring-indigo-200";

export default function ThresholdExplorerAdminPage() {
  const [mode, setMode] = useState<"cases" | "counts">("cases");
  const [threshold, setThreshold] = useState("0.5");
  const [casesText, setCasesText] = useState("");
  const [tp, setTp] = useState("0"); const [fp, setFp] = useState("0");
  const [fn, setFn] = useState("0"); const [tn, setTn] = useState("0");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    admin.labs.getThresholdLab()
      .then((c) => {
        setMode(c.mode);
        setThreshold(String(c.threshold));
        setCasesText(casesToText(c.cases));
        setTp(String(c.tp)); setFp(String(c.fp));
        setFn(String(c.fn)); setTn(String(c.tn));
        setLoaded(true);
      })
      .catch((e) => setMsg({ kind: "err", text: errMsg(e) }));
  }, []);

  const parsed = useMemo(() => parseCasesText(casesText), [casesText]);
  const nPos = parsed.cases.filter((c) => c.actual === 1).length;
  const nNeg = parsed.cases.length - nPos;

  async function save() {
    setBusy(true); setMsg(null);
    try {
      const cfg: ThresholdExplorerConfig = {
        mode,
        threshold: Number(threshold) || 0.5,
        cases: parsed.cases,
        tp: Number(tp) || 0, fp: Number(fp) || 0,
        fn: Number(fn) || 0, tn: Number(tn) || 0,
      };
      await admin.labs.saveThresholdLab(cfg);
      setMsg({ kind: "ok", text: "Saved — live on the public page now." });
    } catch (e) {
      setMsg({ kind: "err", text: errMsg(e) });
    } finally {
      setBusy(false);
    }
  }

  const canSave = loaded && !busy &&
    (mode === "counts" || (parsed.errors.length === 0 && parsed.cases.length >= 2));

  return (
    <div className="p-8 max-w-3xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Threshold Explorer</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Controls the dataset behind the public lab at{" "}
          <Link href="/labs/threshold-explorer" target="_blank"
                className="text-indigo-600 hover:underline">
            /labs/threshold-explorer ↗
          </Link>
          . Changes go live on the page&apos;s next load.
        </p>
      </header>

      {msg && (
        <div className={`p-3 rounded-lg mb-4 text-sm border ${
          msg.kind === "ok"
            ? "bg-emerald-50 border-emerald-200 text-emerald-800"
            : "bg-rose-50 border-rose-200 text-rose-700"
        }`}>
          {msg.text}
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Mode</label>
          <div className="grid sm:grid-cols-2 gap-3">
            <button type="button" onClick={() => setMode("cases")}
                    className={`text-left rounded-xl border-2 p-3.5 text-sm transition ${
                      mode === "cases"
                        ? "border-indigo-500 bg-indigo-50"
                        : "border-slate-200 hover:border-slate-300"
                    }`}>
              <span className="block font-semibold mb-0.5">Interactive (cases)</span>
              Each case is a score + actual label. Slider, matrix, ROC &amp; PR all live.
            </button>
            <button type="button" onClick={() => setMode("counts")}
                    className={`text-left rounded-xl border-2 p-3.5 text-sm transition ${
                      mode === "counts"
                        ? "border-indigo-500 bg-indigo-50"
                        : "border-slate-200 hover:border-slate-300"
                    }`}>
              <span className="block font-semibold mb-0.5">Snapshot (counts)</span>
              Only the four totals. Slider and curves hidden on the public page.
            </button>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Default threshold
          </label>
          <input value={threshold} onChange={(e) => setThreshold(e.target.value)}
                 className={input + " max-w-[120px]"} inputMode="decimal" />
          <p className="text-xs text-slate-500 mt-1">
            Where the slider starts for every visitor (0.01 – 0.99).
          </p>
        </div>

        <div className={mode === "cases" ? "" : "opacity-40 pointer-events-none"}>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Cases — one per line: <code className="bg-slate-100 px-1 rounded">score, actual</code>{" "}
            (1 = positive, 0 = negative)
          </label>
          <textarea value={casesText} onChange={(e) => setCasesText(e.target.value)}
                    rows={10} spellCheck={false}
                    className={input + " font-mono text-xs leading-6"} />
          <p className="text-xs mt-1">
            {parsed.errors.length > 0 ? (
              <span className="text-rose-600 font-medium">
                ✕ {parsed.errors.length} bad line{parsed.errors.length === 1 ? "" : "s"}:{" "}
                {parsed.errors.slice(0, 5).map((e) => `line ${e.line}`).join(", ")}
                {parsed.errors.length > 5 ? "…" : ""} — expected “score, actual”
                with score 0–1 and actual 0/1.
              </span>
            ) : (
              <span className="text-emerald-700 font-medium">
                ✓ {parsed.cases.length} case{parsed.cases.length === 1 ? "" : "s"} ·{" "}
                {nPos} positive / {nNeg} negative
                {parsed.cases.length >= 2 && (nPos === 0 || nNeg === 0) &&
                  " — needs at least one of each class"}
              </span>
            )}
          </p>
        </div>

        <div className={mode === "counts" ? "" : "opacity-40 pointer-events-none"}>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Snapshot counts
          </label>
          <div className="grid grid-cols-4 gap-3">
            {([["TP", tp, setTp], ["FP", fp, setFp],
               ["FN", fn, setFn], ["TN", tn, setTn]] as const).map(([k, v, set]) => (
              <div key={k}>
                <span className="block text-xs text-slate-500 mb-1">{k}</span>
                <input value={v} onChange={(e) => set(e.target.value)}
                       className={input} inputMode="numeric" />
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <button onClick={save} disabled={!canSave}
                  className="px-5 py-2.5 bg-indigo-600 text-white text-sm font-semibold
                             rounded-lg hover:bg-indigo-700 disabled:opacity-40">
            {busy ? "Saving…" : "Save & publish"}
          </button>
          <Link href="/labs/threshold-explorer" target="_blank"
                className="px-4 py-2.5 border border-slate-300 text-slate-700 text-sm
                           rounded-lg hover:bg-slate-50">
            Preview ↗
          </Link>
          <span className="text-xs text-slate-500">Audit-logged like every admin change.</span>
        </div>
      </div>
    </div>
  );
}
