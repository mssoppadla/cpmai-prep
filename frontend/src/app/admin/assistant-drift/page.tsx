"use client";
/**
 * /admin/assistant-drift — operator dashboard for the assistant's
 * post-response drift detector.
 *
 * Headline framing: "is the LLM going off the rails, and is one flow
 * better than the other?" Side-by-side cards compare the legacy
 * (keyword classifier + single handler) flow with the agentic (LLM
 * tool routing + synthesis) flow. The card layout doesn't change
 * with rollout state — when an operator first turns on `flow=agentic`
 * or starts a `percent:N` rollout, agentic events start landing in
 * the existing column.
 *
 * When shadow mode is sampling (assistant.flow=shadow,
 * shadow_sampling_rate > 0), a third "Shadow agentic" card surfaces
 * to compare drift between the legacy primary and the shadow
 * agentic side without affecting users.
 *
 * Below the headline cards, a recent-events table lets the operator
 * drill into individual events: see the original question, the LLM
 * response excerpt, the retrieval state, and which rule fired. Filter
 * by flow / reason / handler.
 */
import { useEffect, useMemo, useState } from "react";
import { admin, ApiError } from "@/lib/api";


type Window = "24h" | "7d" | "30d";


// Friendly labels for the drift reason → operator action mapping.
// Each reason has a one-line "what does this mean" hint so the
// dashboard is self-explanatory without reading the docstring.
const REASON_LABEL: Record<string, { title: string; hint: string }> = {
  refused_with_context: {
    title: "Refused with context",
    hint:  "LLM said 'outside scope' but RAG had relevant chunks. " +
           "Edit the handler's SYSTEM prompt or add the topic to allowed_exceptions.",
  },
  empty_response: {
    title: "Empty response",
    hint:  "LLM returned <20 chars. Usually a provider hiccup; " +
           "occasionally a too-strict guardrail.",
  },
  missing_citation: {
    title: "Missing citation",
    hint:  "Chunks retrieved but response had no [Source N] reference. " +
           "User got an answer without provenance.",
  },
  invented_citation: {
    title: "Invented citation",
    hint:  "Response cited a Source number that wasn't in the retrieved set — " +
           "hallucinated provenance.",
  },
};


export default function AssistantDriftPage() {
  const [window, setWindow] = useState<Window>("7d");
  const [summary, setSummary] = useState<Awaited<ReturnType<typeof admin.assistantDrift.summary>> | null>(null);
  const [events, setEvents] = useState<Awaited<ReturnType<typeof admin.assistantDrift.events>> | null>(null);
  const [filterFlow, setFilterFlow] = useState<
    "" | "legacy" | "agentic" | "shadow_agentic"
  >("");
  const [filterReason, setFilterReason] = useState<string>("");
  const [filterHandler, setFilterHandler] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);

  async function reload() {
    setErr(null);
    try {
      const [s, e] = await Promise.all([
        admin.assistantDrift.summary(window),
        admin.assistantDrift.events({
          window,
          flow:    filterFlow || undefined,
          reason:  filterReason || undefined,
          handler: filterHandler || undefined,
          limit: 50,
        }),
      ]);
      setSummary(s); setEvents(e);
    } catch (e) {
      setErr((e as ApiError).body?.message ?? String(e));
    }
  }
  useEffect(() => { reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ },
            [window, filterFlow, filterReason, filterHandler]);

  // Per-(flow, reason) lookup so the side-by-side card grid can ask
  // "how many invented_citation events on legacy in this window?" in
  // O(1). Pre-built once per summary fetch.
  const byFlowReason = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of summary?.by_flow_reason ?? []) {
      m.set(`${r.flow}:${r.reason}`, r.count);
    }
    return m;
  }, [summary]);

  const reasons = Object.keys(REASON_LABEL);
  // "Active" = at least one turn OR drift event in the window. This
  // controls whether the column shows real numbers vs the muted
  // "no data yet" state.
  const agenticActive = (summary?.totals.agentic.turns ?? 0) > 0
                     || (summary?.totals.agentic.drift_events ?? 0) > 0;
  // Shadow card appears only when the backend actually returned a
  // shadow_agentic bucket — which only happens when at least one
  // shadow event landed in the window. Empty shadow column is
  // visual noise.
  const shadow = summary?.totals.shadow_agentic;

  return (
    <div className="p-8 max-w-6xl space-y-6">
      <header className="flex items-baseline justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Assistant drift</h1>
          <p className="text-slate-600 mt-1 text-sm max-w-2xl">
            Post-response checks that catch when the LLM goes off the rails.
            Compares the legacy (regex classifier + single handler) flow
            with the agentic (LLM tool routing) flow once both are running.
            Enable detection in <code className="text-xs bg-slate-100 px-1
              rounded">/admin/settings → assistant.drift_detection_enabled</code>.
          </p>
        </div>
        <select value={window}
                onChange={(e) => setWindow(e.target.value as Window)}
                className="px-3 py-1.5 text-sm border border-slate-300 rounded">
          <option value="24h">Last 24 hours</option>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
        </select>
      </header>

      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700
                              p-3 rounded-lg text-sm">{err}</div>}

      {/* Side-by-side comparison cards. Legacy + agentic columns
          always render so the operator can immediately see "is agentic
          better than legacy?" — when agentic hasn't been turned on
          yet, that column shows the muted "no data yet" state instead
          of misleading 0% rates.

          The third "Shadow agentic" column surfaces only when shadow
          mode has actually been sampling — i.e., the backend returned
          a shadow_agentic bucket. Empty-column noise is avoided. */}
      {summary && (
        <section className={`grid grid-cols-1 gap-4 ${
          shadow ? "lg:grid-cols-3" : "md:grid-cols-2"
        }`}>
          <FlowCard title="Legacy"
                    subtitle="keyword classifier + single handler"
                    turns={summary.totals.legacy.turns}
                    driftEvents={summary.totals.legacy.drift_events}
                    reasons={reasons.map(r => ({
                      reason: r,
                      count: byFlowReason.get(`legacy:${r}`) ?? 0,
                    }))}
                    active />
          <FlowCard title="Agentic"
                    subtitle="LLM tool routing + synthesis"
                    turns={summary.totals.agentic.turns}
                    driftEvents={summary.totals.agentic.drift_events}
                    reasons={reasons.map(r => ({
                      reason: r,
                      count: byFlowReason.get(`agentic:${r}`) ?? 0,
                    }))}
                    active={agenticActive} />
          {shadow && (
            <FlowCard title="Shadow agentic"
                      subtitle="background-only; logged for offline comparison"
                      turns={shadow.turns}
                      driftEvents={shadow.drift_events}
                      reasons={reasons.map(r => ({
                        reason: r,
                        count: byFlowReason.get(`shadow_agentic:${r}`) ?? 0,
                      }))}
                      active />
          )}
        </section>
      )}

      {/* Recent events table. Filters compose AND-style. */}
      <section className="bg-white rounded-xl border border-slate-200">
        <header className="px-5 py-3 border-b border-slate-200 flex
                           items-center justify-between flex-wrap gap-3">
          <h2 className="font-semibold text-slate-900 text-sm">Recent events</h2>
          <div className="flex items-center gap-2 text-xs">
            <select value={filterFlow}
                    onChange={(e) => setFilterFlow(e.target.value as never)}
                    className="px-2 py-1 border border-slate-300 rounded">
              <option value="">All flows</option>
              <option value="legacy">Legacy</option>
              <option value="agentic">Agentic</option>
              <option value="shadow_agentic">Shadow agentic</option>
            </select>
            <select value={filterReason}
                    onChange={(e) => setFilterReason(e.target.value)}
                    className="px-2 py-1 border border-slate-300 rounded">
              <option value="">All reasons</option>
              {reasons.map(r => (
                <option key={r} value={r}>{REASON_LABEL[r].title}</option>
              ))}
            </select>
            <input value={filterHandler}
                   onChange={(e) => setFilterHandler(e.target.value)}
                   placeholder="handler"
                   className="px-2 py-1 border border-slate-300 rounded w-24" />
          </div>
        </header>
        <div className="divide-y divide-slate-100">
          {events?.events.length === 0 && (
            <div className="px-5 py-6 text-sm text-slate-500 text-center">
              No drift events match. If detection is off, enable it in{" "}
              <code className="bg-slate-100 px-1 rounded text-xs">
                /admin/settings
              </code>.
            </div>
          )}
          {events?.events.map(e => (
            <DriftEventRow key={e.id} event={e} />
          ))}
        </div>
      </section>
    </div>
  );
}


// ============================================================ FlowCard

function FlowCard({
  title, subtitle, turns, driftEvents, reasons, active,
}: {
  title: string;
  subtitle: string;
  /** ``null`` for shadow agentic — shadow doesn't write AssistantLog
   *  rows, so there's no turn baseline for a drift rate. The card
   *  renders absolute counts only in that case. */
  turns: number | null;
  driftEvents: number;
  reasons: { reason: string; count: number }[];
  active: boolean;
}) {
  // Three rendering modes:
  //   * Active + turns known → "12 drift events of 1,043 turns · 1.15%"
  //   * Active + turns=null  → "6 drift events (no turn baseline — shadow doesn't write turns)"
  //   * Inactive             → muted "no data yet"
  let rate = "—";
  let subtext = "no data yet";
  if (active) {
    if (turns === null) {
      subtext = "shadow events; no turn baseline for a rate";
    } else if (turns > 0) {
      rate = ((driftEvents / turns) * 100).toFixed(2) + "%";
      subtext = `of ${turns} turns · ${rate}`;
    } else {
      subtext = "0 turns yet — drift detection on but no traffic";
    }
  }

  return (
    <div className={`bg-white rounded-xl border p-5 ${
      active ? "border-slate-200" : "border-slate-200 opacity-75"
    }`}>
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <h3 className="font-semibold text-slate-900">{title}</h3>
          <p className="text-xs text-slate-500">{subtitle}</p>
        </div>
        {!active && (
          <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5
                            rounded border border-slate-200">
            not active
          </span>
        )}
      </div>
      <div className="mt-4 flex items-baseline gap-3">
        <div className="text-3xl font-bold text-slate-900">
          {active ? driftEvents : "—"}
        </div>
        <div className="text-sm text-slate-500">{subtext}</div>
      </div>
      <ul className="mt-4 space-y-1.5 text-sm">
        {reasons.map(({ reason, count }) => {
          const label = REASON_LABEL[reason]?.title ?? reason;
          return (
            <li key={reason} className="flex items-center justify-between
                                          text-slate-700">
              <span>{label}</span>
              <span className={count > 0 ? "font-semibold" : "text-slate-400"}>
                {active ? count : "—"}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}


// ============================================================ DriftEventRow

function DriftEventRow({ event }: {
  event: {
    id: number;
    reason: string;
    metadata: Record<string, unknown>;
    created_at: string;
  };
}) {
  const m = event.metadata;
  const reasonInfo = REASON_LABEL[event.reason] ?? {
    title: event.reason, hint: "",
  };
  const flow = String(m.flow ?? "legacy");
  const handler = String(m.handler ?? "—");
  const intent  = m.intent ? String(m.intent) : "—";
  const question = String(m.question_excerpt ?? "");
  const response = String(m.response_excerpt ?? "");
  const detail = String(m.detail ?? "");

  return (
    <div className="px-5 py-4 hover:bg-slate-50">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-slate-900 text-sm">
            {reasonInfo.title}
          </span>
          <Badge>{flow}</Badge>
          <Badge>{handler}</Badge>
          {intent !== "—" && <Badge muted>{intent}</Badge>}
          <span className="text-xs text-slate-500">
            {new Date(event.created_at).toLocaleString()}
          </span>
        </div>
      </div>
      {detail && (
        <div className="mt-1 text-xs text-slate-500 italic">{detail}</div>
      )}
      <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
        <div>
          <div className="text-slate-500 font-medium mb-1">Question</div>
          <div className="text-slate-700 bg-slate-50 px-2 py-1.5 rounded">
            {question || "—"}
          </div>
        </div>
        <div>
          <div className="text-slate-500 font-medium mb-1">Response excerpt</div>
          <div className="text-slate-700 bg-slate-50 px-2 py-1.5 rounded">
            {response || "—"}
          </div>
        </div>
      </div>
      {reasonInfo.hint && (
        <div className="mt-2 text-xs text-slate-500">{reasonInfo.hint}</div>
      )}
    </div>
  );
}


function Badge({ children, muted = false }: {
  children: React.ReactNode; muted?: boolean;
}) {
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded border font-mono ${
      muted ? "bg-slate-50 text-slate-500 border-slate-200"
            : "bg-indigo-50 text-indigo-700 border-indigo-200"
    }`}>
      {children}
    </span>
  );
}
