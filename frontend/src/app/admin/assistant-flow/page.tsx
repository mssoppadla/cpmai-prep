"use client";
/**
 * /admin/assistant-flow — dedicated control surface for the
 * assistant.flow toggle and related agentic-config settings.
 *
 * The toggle is just a settings_store key (assistant.flow), so an
 * operator COULD edit it on the generic /admin/settings page. This
 * dedicated page exists because:
 *
 *   1. The flow setting has structured form: legacy / agentic /
 *      percent:N / shadow. A free-text field on the generic page
 *      makes typos easy ("percent:9999" rejected at PATCH but only
 *      after the operator clicks Save). Radio buttons + a slider
 *      make the valid shape obvious.
 *
 *   2. percent:N is a gradual rollout — the operator wants to see
 *      "at the current N, which cohort would my representative
 *      anon visitor land in?" before committing the change. The
 *      preview panel answers that without leaving the page.
 *
 *   3. Tied settings (tools_max_calls, shadow_sampling_rate) only
 *      matter in certain modes. Conditional rendering hides the
 *      slider when shadow isn't selected.
 *
 * Writes go through the existing PATCH /admin/settings/{key} endpoint
 * — no new write API. The /admin/assistant-flow/{state,preview} GET
 * endpoints just give us one-round-trip reads + live preview.
 */
import { useEffect, useMemo, useState } from "react";
import { admin, errMsg } from "@/lib/api";


type FlowMode = "legacy" | "agentic" | "percent" | "shadow";


function parseFlow(raw: string): { mode: FlowMode; percent: number } {
  const s = (raw || "legacy").trim().toLowerCase();
  if (s.startsWith("percent:")) {
    const n = parseInt(s.split(":", 2)[1], 10);
    return { mode: "percent", percent: Number.isFinite(n) ? n : 0 };
  }
  if (s === "agentic" || s === "shadow") return { mode: s, percent: 0 };
  return { mode: "legacy", percent: 0 };
}


function serialiseFlow(mode: FlowMode, percent: number): string {
  if (mode === "percent") return `percent:${Math.max(0, Math.min(100, percent))}`;
  return mode;
}


export default function AssistantFlowPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving]   = useState(false);
  const [err, setErr]         = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  // Form state — initialised from the backend's /state response.
  // We hold both `mode` and `percent` separately so a user toggling
  // between "agentic" and "percent" doesn't lose their slider value.
  const [mode, setMode]                 = useState<FlowMode>("legacy");
  const [percent, setPercent]           = useState(10);
  const [toolsMaxCalls, setToolsMaxCalls] = useState(4);
  const [shadowRate, setShadowRate]     = useState(0.0);
  const [routerSystem, setRouterSystem] = useState("");
  const [synthSystem, setSynthSystem]   = useState("");

  // Mirror of what the backend SAYS the current state is — used to
  // compute what's been changed since load (so Save only PATCHes
  // dirty fields).
  const [server, setServer] = useState<{
    flow: string;
    tools_max_calls: number;
    router_system: string;
    synthesis_system: string;
    shadow_sampling_rate: number;
  } | null>(null);

  async function reload() {
    setLoading(true); setErr(null);
    try {
      const s = await admin.assistantFlow.state();
      const parsed = parseFlow(s.flow);
      setMode(parsed.mode);
      // Preserve last percent value if mode wasn't percent — handy
      // when an operator switches off percent and back without
      // wanting to re-type the number.
      if (parsed.mode === "percent") setPercent(parsed.percent);
      setToolsMaxCalls(s.tools_max_calls);
      setShadowRate(s.shadow_sampling_rate);
      setRouterSystem(s.router_system);
      setSynthSystem(s.synthesis_system);
      setServer(s);
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { reload(); /* eslint-disable-next-line */ }, []);

  // Computed flow string — what we'd write if the operator hit Save.
  const desiredFlow = serialiseFlow(mode, percent);

  // Dirty-detection — only PATCH changed fields so we don't add audit-
  // log noise for no-op saves and don't bump updated_by uselessly.
  const dirty = useMemo(() => {
    if (!server) return new Set<string>();
    const out = new Set<string>();
    if (server.flow !== desiredFlow) out.add("assistant.flow");
    if (server.tools_max_calls !== toolsMaxCalls)
      out.add("assistant.agentic.tools_max_calls");
    if (server.shadow_sampling_rate !== shadowRate)
      out.add("assistant.agentic.shadow_sampling_rate");
    if (server.router_system !== routerSystem)
      out.add("assistant.agentic.router_system");
    if (server.synthesis_system !== synthSystem)
      out.add("assistant.agentic.synthesis_system");
    return out;
  }, [server, desiredFlow, toolsMaxCalls, shadowRate, routerSystem, synthSystem]);

  async function save() {
    setSaving(true); setErr(null);
    try {
      // Sequential PATCHes — each one round-trips through the
      // /admin/settings validator. The dirty set is small (5 keys
      // max) so serial is fine; doing parallel Promise.all would save
      // ~50ms but lose ordered error reporting.
      if (dirty.has("assistant.flow"))
        await admin.settings.update("assistant.flow", desiredFlow);
      if (dirty.has("assistant.agentic.tools_max_calls"))
        await admin.settings.update(
          "assistant.agentic.tools_max_calls", toolsMaxCalls);
      if (dirty.has("assistant.agentic.shadow_sampling_rate"))
        await admin.settings.update(
          "assistant.agentic.shadow_sampling_rate", shadowRate);
      if (dirty.has("assistant.agentic.router_system"))
        await admin.settings.update(
          "assistant.agentic.router_system", routerSystem);
      if (dirty.has("assistant.agentic.synthesis_system"))
        await admin.settings.update(
          "assistant.agentic.synthesis_system", synthSystem);
      setSavedAt(new Date());
      await reload();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-8 max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">Assistant flow</h1>
        <p className="text-slate-600 mt-1 text-sm max-w-2xl">
          Switch the chat orchestration pipeline between the legacy
          keyword-classifier flow and the agentic tool-routing flow,
          with optional percent rollout and shadow-mode A/B comparison.
          Changes take effect immediately — no redeploy.
        </p>
      </header>

      {err && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700
                          p-3 rounded-lg text-sm" role="alert">{err}</div>
      )}

      {loading ? (
        <div className="text-slate-500">Loading current state…</div>
      ) : (
        <>
          <section className="bg-white rounded-xl border border-slate-200 p-5">
            <h2 className="font-semibold text-slate-900 mb-3">Flow mode</h2>
            <div className="space-y-2">
              <ModeRadio name="legacy" current={mode} setMode={setMode}
                         title="Legacy"
                         subtitle="Keyword classifier + single handler (default)" />
              <ModeRadio name="agentic" current={mode} setMode={setMode}
                         title="Agentic"
                         subtitle="LLM tool routing + synthesis, all traffic" />
              <ModeRadio name="percent" current={mode} setMode={setMode}
                         title="Percent rollout"
                         subtitle="Gradual cutover — N% of users get agentic,
                                   bucketed deterministically by identity hash" />
              {mode === "percent" && (
                <div className="ml-7 mt-1 mb-2">
                  <div className="flex items-center gap-3">
                    <input type="range" min={0} max={100} step={1}
                            value={percent}
                            onChange={(e) => setPercent(parseInt(e.target.value, 10))}
                            className="flex-1 max-w-sm" />
                    <span className="font-mono text-sm w-12 text-right">
                      {percent}%
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">
                    {percent === 0
                      ? "Everyone on legacy."
                      : percent === 100
                        ? "Everyone on agentic — same as picking Agentic above."
                        : `Buckets 0–${percent - 1} land on agentic; rest stay on legacy.`}
                  </p>
                </div>
              )}
              <ModeRadio name="shadow" current={mode} setMode={setMode}
                         title="Shadow"
                         subtitle="Legacy answers users; agentic also runs in
                                   the background for offline comparison" />
              {mode === "shadow" && (
                <div className="ml-7 mt-1 mb-2">
                  <div className="flex items-center gap-3">
                    <input type="range" min={0} max={1} step={0.05}
                            value={shadowRate}
                            onChange={(e) => setShadowRate(parseFloat(e.target.value))}
                            className="flex-1 max-w-sm" />
                    <span className="font-mono text-sm w-16 text-right">
                      {(shadowRate * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">
                    Fraction of requests on which the agentic side
                    actually runs. {shadowRate === 0 && "0% — shadow disabled."}
                    {shadowRate > 0 && shadowRate < 1 &&
                      ` ${Math.round(shadowRate * 100)}% of legacy requests also run agentic; doubles their cost.`}
                    {shadowRate === 1 && " Every legacy request also runs agentic (2× LLM cost on every turn)."}
                  </p>
                </div>
              )}
            </div>
          </section>

          <section className="bg-white rounded-xl border border-slate-200 p-5">
            <h2 className="font-semibold text-slate-900 mb-3">
              Agentic tuning
            </h2>
            <p className="text-xs text-slate-500 mb-4">
              Only relevant when the agentic flow runs (mode ≠ legacy).
              These edits don&apos;t take effect until you save.
            </p>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Tools max calls
                </label>
                <input type="number" min={1} max={10}
                        value={toolsMaxCalls}
                        onChange={(e) => setToolsMaxCalls(
                          parseInt(e.target.value, 10))}
                        className="px-3 py-1.5 border border-slate-300 rounded
                                   w-24 text-sm" />
                <p className="text-xs text-slate-500 mt-1">
                  Hard cap on tool invocations per chat turn
                  (including router re-plans). Cost guardrail.
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Router system prompt
                  <span className="text-slate-400 font-normal ml-1">
                    (leave blank to use shipped default)
                  </span>
                </label>
                <textarea value={routerSystem}
                          onChange={(e) => setRouterSystem(e.target.value)}
                          rows={6} maxLength={8000}
                          placeholder="(using shipped default)"
                          className="w-full px-3 py-2 text-sm font-mono
                                     border border-slate-300 rounded" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Synthesis system prompt
                  <span className="text-slate-400 font-normal ml-1">
                    (leave blank to use shipped default)
                  </span>
                </label>
                <textarea value={synthSystem}
                          onChange={(e) => setSynthSystem(e.target.value)}
                          rows={6} maxLength={8000}
                          placeholder="(using shipped default)"
                          className="w-full px-3 py-2 text-sm font-mono
                                     border border-slate-300 rounded" />
              </div>
            </div>
          </section>

          <section className="bg-white rounded-xl border border-slate-200 p-5
                                flex items-center justify-between gap-3">
            <div className="text-xs text-slate-500">
              {dirty.size > 0
                ? <>Unsaved changes in <strong>{dirty.size}</strong> field{dirty.size === 1 ? "" : "s"}.</>
                : savedAt
                  ? <>Saved at {savedAt.toLocaleTimeString()}.</>
                  : "No changes."}
            </div>
            <button onClick={save}
                    disabled={saving || dirty.size === 0}
                    className="px-4 py-2 bg-indigo-600 text-white text-sm
                               font-medium rounded hover:bg-indigo-700
                               disabled:opacity-50 disabled:cursor-not-allowed">
              {saving ? "Saving…" : `Save ${dirty.size > 0 ? `(${dirty.size})` : ""}`}
            </button>
          </section>

          <PreviewPanel />
        </>
      )}
    </div>
  );
}


function ModeRadio({
  name, current, setMode, title, subtitle,
}: {
  name: FlowMode;
  current: FlowMode;
  setMode: (v: FlowMode) => void;
  title: string;
  subtitle: string;
}) {
  const id = `flow-mode-${name}`;
  return (
    <label htmlFor={id}
           className={`flex items-start gap-3 p-2 rounded cursor-pointer
                       hover:bg-slate-50 ${
                         current === name ? "bg-indigo-50" : ""
                       }`}>
      <input type="radio" id={id} name="flow-mode"
              checked={current === name}
              onChange={() => setMode(name)}
              className="mt-1" />
      <div>
        <div className="font-medium text-slate-900 text-sm">{title}</div>
        <div className="text-xs text-slate-500">{subtitle}</div>
      </div>
    </label>
  );
}


// ============================================================ preview

function PreviewPanel() {
  const [anonId, setAnonId] = useState("");
  const [userId, setUserId] = useState("");
  const [result, setResult] = useState<Awaited<
    ReturnType<typeof admin.assistantFlow.preview>
  > | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState<string | null>(null);

  async function run() {
    setBusy(true); setErr(null);
    try {
      const r = await admin.assistantFlow.preview({
        as_anon_id: anonId.trim() || undefined,
        as_user_id: userId.trim()
                      ? parseInt(userId.trim(), 10)
                      : undefined,
      });
      setResult(r);
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-white rounded-xl border border-slate-200 p-5">
      <h2 className="font-semibold text-slate-900 mb-1">Live cohort preview</h2>
      <p className="text-xs text-slate-500 mb-4">
        Given the current flow setting + the identity you enter below,
        which flow would this user land on RIGHT NOW? Use this to
        confirm a representative user is on the right side of a
        percent rollout. Note: the cohort bucket re-rolls daily, so
        this is a snapshot, not a permanent assignment.
      </p>
      <div className="flex items-end gap-3 flex-wrap">
        <div>
          <label className="block text-xs text-slate-600 mb-1">
            Anonymous ID
          </label>
          <input value={anonId}
                  onChange={(e) => setAnonId(e.target.value)}
                  placeholder="e.g. paste from /admin/leads"
                  className="px-3 py-1.5 text-sm border border-slate-300
                             rounded w-72 font-mono" />
        </div>
        <div className="text-slate-400 text-xs px-1 pb-2">OR</div>
        <div>
          <label className="block text-xs text-slate-600 mb-1">
            User ID
          </label>
          <input type="number" min={1}
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  placeholder="numeric"
                  className="px-3 py-1.5 text-sm border border-slate-300
                             rounded w-32 font-mono" />
        </div>
        <button onClick={run} disabled={busy}
                className="px-4 py-1.5 bg-slate-700 text-white text-sm
                           rounded hover:bg-slate-800 disabled:opacity-50">
          {busy ? "…" : "Preview"}
        </button>
      </div>
      {err && (
        <div className="mt-3 bg-rose-50 border border-rose-200 text-rose-700
                          px-3 py-2 rounded text-sm">{err}</div>
      )}
      {result && (
        <div className="mt-4 bg-slate-50 rounded p-3 text-sm space-y-1.5">
          <div>
            <span className="text-slate-500">Primary flow:</span>{" "}
            <span className={`font-mono font-semibold ${
              result.decision.primary === "agentic"
                ? "text-violet-700" : "text-slate-900"
            }`}>{result.decision.primary}</span>
          </div>
          {result.decision.shadow && (
            <div>
              <span className="text-slate-500">Shadow flow:</span>{" "}
              <span className="font-mono">{result.decision.shadow}</span>
              <span className="text-xs text-slate-500 ml-2">
                (runs in background, logged for comparison)
              </span>
            </div>
          )}
          <div>
            <span className="text-slate-500">Cohort bucket:</span>{" "}
            <span className="font-mono">{result.cohort_bucket}</span>
            <span className="text-xs text-slate-500 ml-2">/ 100</span>
          </div>
          <div>
            <span className="text-slate-500">Reason:</span>{" "}
            <span className="text-slate-700">{result.decision.reason}</span>
          </div>
        </div>
      )}
    </section>
  );
}
