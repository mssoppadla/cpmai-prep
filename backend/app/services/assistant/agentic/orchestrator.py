"""Agentic orchestrator — router → tool exec → (re-plan?) → synthesis.

Plain-Python state machine, NOT LangGraph. Once the conditional
re-plan landed (PR #2) the graph still has only four reachable nodes
with linear transitions; LangGraph's value would still be mostly
boilerplate. Adoption stays deferred until we hit a real branching
need (multi-round tool chains, parallel-tool fan-out, sub-graphs).

Flow for one chat turn::

  ┌──────────────────────────────────────────────────────────────────┐
  │ 1. Build router system prompt (admin-tunable + tools[])          │
  │ 2. Call provider.complete_with_tools()                  ← LLM #1 │
  │ 3. If router emitted NO tool_calls:                              │
  │       → return router's text as the answer (no LLM #2)           │
  │    Else:                                                         │
  │ 4.    Execute each tool_call (capped by remaining budget):       │
  │         - registry.get(name) — unknown name = error              │
  │         - check requires_user — refuse if anon                   │
  │         - coerce_args via JSON-schema                            │
  │         - tool.execute(ctx, args) — never raises                 │
  │ 5.    RE-PLAN CHECK: if every result was EMPTY/ERROR/auth-refuse │
  │       AND we still have budget under ``tools_max_calls``, give   │
  │       the router one more shot with the prior tool results in    │
  │       its message context. Bounded to ONE re-plan (V1).          │
  │ 6.    Build synthesis system prompt with all tool results as     │
  │       evidence + admin guardrail preamble                        │
  │ 7.    Call provider.complete()                          ← LLM #2 │
  │ 8.    Aggregate citations + suggested_actions from OK results    │
  │ 9.    Return AgenticResult                                       │
  └──────────────────────────────────────────────────────────────────┘

What re-plan changes operationally:

  * Best-case turn (router picks well): 1 router + 1 synthesis = 2
    generation calls. Identical to V1 cost.
  * Worst-case turn (router re-plans): 2 router + 1 synthesis = 3
    generation calls. ~1.5x V1 cost on the few turns where it fires.
  * Budget guard: ``tools_max_calls`` is total tool invocations per
    turn (default 4). If iteration 1 uses 4 tools, no re-plan can
    happen — we're already at the cap. Synthesis runs on whatever
    evidence we have.

What this module still does NOT include (deferred):

  * **Multi-round tool chains** — synthesis cannot call more tools.
    One round of tools (possibly across iterations) + one synthesis
    pass per turn.
  * **Parallel tool fan-out** — tool executions are sequential within
    an iteration. Not a correctness issue (tools are pure), more an
    optimisation. Adopt when latency observation warrants it.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.settings_store import settings_store
from app.models.user import User
from app.schemas.assistant import AssistantRequest
from app.services.assistant.agentic import registry
from app.services.assistant.agentic.types import (
    ToolContext, ToolResult, ToolStatus, coerce_args,
)
from app.services.assistant.providers.base import (
    LLMProvider, ToolCall, ToolCallingResponse,
)
from app.services.assistant.system_prompt import with_preamble

log = logging.getLogger("assistant.agentic")


# ====================================================== prompts (shipped defaults)

# Both router and synthesis system prompts are admin-tunable via
# assistant.agentic.router_system / synthesis_system. Empty setting
# = use the shipped default below. Tune via Runtime Settings, not by
# editing this file (or operators lose their override on next deploy).

DEFAULT_ROUTER_SYSTEM = """\
You are the routing brain for the CPMAI Prep assistant. The user's
question is below. Decide which of the available tools should be
called to gather evidence for the answer.

Rules:
  1. Call AS FEW tools as necessary. One tool per topic is the
     baseline; multi-topic questions justify multiple calls.
  2. Tools named *_search take a "query" — pass the user's wording
     verbatim unless they asked about multiple distinct topics, in
     which case make one call per topic.
  3. For pricing / billing / plan questions, use pricing_lookup.
     For "what is X / explain Y" use content_search. For
     certification process / eligibility / scheduling questions,
     use faq_search. They overlap by design — pick the one whose
     description best fits, or call both if you're unsure.
  4. For "where do I register / what's on the exam" → pmi_reference
     with intent="course" or "eco" respectively.
  5. For "my account / my subscription / when do I expire" →
     account_state. For "my last exam attempts / how am I doing" →
     user_insights. These two require the user to be signed in;
     if the chat context lacks a signed-in user, do NOT call them.
  6. For "I want to talk to a human" or when no tool can answer →
     human_escalation with a one-sentence reason.
  7. If the question is conversational (greeting, thanks, very
     short) — answer directly without picking any tool.

You are NOT the final answerer — your job is just to pick the
right tools. The synthesis step will compose the actual answer
from the tool results.
"""

DEFAULT_SYNTHESIS_SYSTEM = """\
You are the CPMAI Prep assistant. You have just received evidence
from one or more tools. Use ONLY this evidence to answer the user's
question. Rules:

  * Cite sources using [Source N] notation matching the chunk
    numbering in the evidence block.
  * If the evidence is empty or doesn't cover the question, say
    so honestly — do not invent facts.
  * Be concise. Prefer 2-5 sentences plus citations.
  * If a tool returned REFUSED_NEED_AUTH (auth required), gently
    ask the user to sign in to access that information.
  * If every tool returned EMPTY/ERROR, acknowledge you don't have
    information and offer to escalate to a human.
"""

# Cap the response we feed back to synthesis — multi-tool evidence
# can balloon, and the synthesis LLM only needs ~the same context
# window the legacy handlers use. Per-tool, per-result cap.
_MAX_TOOL_CONTENT_CHARS = 4000


# ============================================================ result type

@dataclass
class AgenticResult:
    """Output of one agentic turn — what the main orchestrator
    needs to render an AssistantResponse + write the drift /
    assistant_log rows.

    Intentionally a flat dict-like shape; the main orchestrator
    converts to the AssistantResponse Pydantic model. Decoupling
    here keeps this module unit-testable without bringing in the
    full HTTP request types.
    """
    message:           str
    citations:         list[dict]        = field(default_factory=list)
    suggested_actions: list[dict]        = field(default_factory=list)
    tools_called:      list[dict]        = field(default_factory=list)
    error:             str | None        = None
    metadata:          dict[str, Any]    = field(default_factory=dict)


# ============================================================ orchestrator

class AgenticOrchestrator:
    """Run one agentic turn against the active LLM provider + the
    registered tool set.

    Stateless across requests — each call to ``handle`` is independent.
    The DB session, current user, and anon_id are threaded via the
    constructor so unit tests can pass mocks.
    """

    def __init__(self, db: Session, provider: LLMProvider):
        self.db = db
        self.provider = provider

    def handle(self, request: AssistantRequest, user: User | None,
                anon_id: str | None) -> AgenticResult:
        """Run the agentic state machine for a single chat turn.

        Returns an AgenticResult — never raises. Provider exceptions,
        tool exceptions, and synthesis exceptions all get caught and
        downgraded into result.error so the main orchestrator can
        write a clean drift-event audit row.
        """
        started = time.monotonic()
        ctx = ToolContext(db=self.db, user=user, anon_id=anon_id)
        history = self._build_history(request)
        tools_schema = [t.to_openai_schema() for t in registry.all_tools()]

        # Budget — total tool invocations allowed across all iterations.
        # Default 4; admin-tunable. Re-plan iterations consume from
        # the same budget so a runaway router can't double-spend.
        remaining_tool_budget = max(1, settings_store.get_int(
            "assistant.agentic.tools_max_calls", 4))

        # All tool results across iterations; synthesis sees the
        # aggregate, dashboard sees the per-call summary list.
        all_results: list[ToolResult] = []

        # Re-plan messages start as the user's request and grow with
        # the OpenAI-format assistant-tool-call + tool-result records
        # if/when a re-plan iteration fires.
        router_messages: list[dict] = list(history)
        replans_fired = 0

        # -------- Iteration 1: Router call ---------------------------
        router_system = with_preamble(self._router_system_prompt())
        try:
            router_resp = self.provider.complete_with_tools(
                router_system, router_messages, tools=tools_schema,
            )
        except Exception as e:
            log.exception("agentic.router_failed")
            return AgenticResult(
                message=_FRIENDLY_ERROR_MESSAGE,
                error=f"router_failed: {e}",
                metadata={"phase": "router", "elapsed_ms": _ms_since(started)},
            )

        # Router-only case — answers directly, no tools needed.
        if not router_resp.tool_calls:
            return AgenticResult(
                message=router_resp.text.strip() or _FRIENDLY_NO_ANSWER,
                tools_called=[],
                metadata={
                    "phase": "router_only",
                    "elapsed_ms": _ms_since(started),
                    "finish_reason": router_resp.finish_reason,
                    "replans_fired": 0,
                },
            )

        # Track total planned tools across iterations so the dashboard
        # can show "router asked for N, we capped at M".
        total_tools_planned = len(router_resp.tool_calls)

        # Execute iteration 1's tool calls (trim to budget).
        planned_calls = router_resp.tool_calls[:remaining_tool_budget]
        iter_results = self._execute_tools(planned_calls, ctx)
        all_results.extend(iter_results)
        remaining_tool_budget -= len(planned_calls)

        # -------- Iteration 2: Re-plan, if needed AND affordable -----
        #
        # Trigger condition: at least one EMPTY result, NO ok result,
        # AND budget left. The EMPTY-gated trigger is deliberate:
        #
        #   * ANY ok result → synthesis has evidence; don't re-plan.
        #   * ERROR-only results → unknown tool / malformed args /
        #     tool exception. These are not fixable by "try harder
        #     with the same prompt" — the router would likely emit
        #     the same broken call again. Synthesis can frame the
        #     error to the user instead.
        #   * REFUSED_NEED_AUTH-only results → user is anonymous;
        #     a re-plan can't change that fact. Synthesis asks them
        #     to sign in.
        #   * EMPTY result(s) → the tools ran cleanly but found
        #     nothing relevant. Different tool(s) might. Worth a
        #     second shot.
        #
        # Why ONLY one re-plan: bounded cost guarantee. Worst-case
        # turn is 2 router + 1 synthesis = 3 generation calls. If
        # real prod observation shows the router needs a 3rd attempt,
        # the loop is an obvious extension.
        any_empty = any(r.status is ToolStatus.EMPTY for r in iter_results)
        any_ok    = any(r.status is ToolStatus.OK    for r in iter_results)
        if any_empty and not any_ok and remaining_tool_budget > 0:
            replans_fired = 1
            # Echo iter-1 tool calls + results back to the router so
            # it has the evidence to decide differently this time.
            router_messages = self._append_tool_round_to_messages(
                router_messages, planned_calls, iter_results,
                router_text=router_resp.text,
            )
            try:
                router_resp2 = self.provider.complete_with_tools(
                    router_system, router_messages, tools=tools_schema,
                )
            except Exception as e:
                # Re-plan failed — don't blow up the turn; synthesise
                # with what iter 1 produced (which is empty/error
                # but at least the user gets SOME answer).
                log.exception("agentic.replan_failed")
                router_resp2 = None
                # Fall through to synthesis on iter-1 results.
                replan_error = f"replan_failed: {e}"
            else:
                replan_error = None

            if router_resp2 is not None and router_resp2.tool_calls:
                total_tools_planned += len(router_resp2.tool_calls)
                planned_calls2 = router_resp2.tool_calls[
                    :remaining_tool_budget]
                iter_results2 = self._execute_tools(
                    planned_calls2, ctx)
                all_results.extend(iter_results2)
                remaining_tool_budget -= len(planned_calls2)
            else:
                # Router chose not to call any tools on re-plan —
                # it has decided to answer (or admit defeat) directly.
                # Synthesis still runs on iter-1 evidence so the user
                # gets a friendly framing rather than the raw router
                # text2.
                pass
        else:
            replan_error = None

        # -------- Synthesis ------------------------------------------
        synth_system = with_preamble(
            self._synthesis_system_prompt(all_results))
        try:
            answer = self.provider.complete(synth_system, history)
        except Exception as e:
            log.exception("agentic.synthesis_failed")
            return AgenticResult(
                message=_FRIENDLY_ERROR_MESSAGE,
                tools_called=_summarise_tool_calls(all_results),
                error=f"synthesis_failed: {e}",
                metadata={
                    "phase": "synthesis",
                    "elapsed_ms": _ms_since(started),
                    "replans_fired": replans_fired,
                },
            )

        # Aggregate citations + suggested_actions from OK results.
        citations: list[dict] = []
        suggested_actions: list[dict] = []
        for r in all_results:
            if r.status is ToolStatus.OK:
                citations.extend(r.citations)
                suggested_actions.extend(r.suggested_actions)

        return AgenticResult(
            message=answer.strip() or _FRIENDLY_NO_ANSWER,
            citations=citations,
            suggested_actions=suggested_actions,
            tools_called=_summarise_tool_calls(all_results),
            error=replan_error,
            metadata={
                "phase": "synthesis",
                "elapsed_ms": _ms_since(started),
                "replans_fired": replans_fired,
                "tools_planned":  total_tools_planned,
                "tools_executed": len(all_results),
                "tools_ok":     sum(1 for r in all_results if r.status is ToolStatus.OK),
                "tools_empty":  sum(1 for r in all_results if r.status is ToolStatus.EMPTY),
                "tools_error":  sum(1 for r in all_results if r.status is ToolStatus.ERROR),
                "tools_refused_need_auth":
                    sum(1 for r in all_results
                        if r.status is ToolStatus.REFUSED_NEED_AUTH),
            },
        )

    # ----------------------------------------------------- helpers

    def _execute_tools(self, calls: list[ToolCall],
                        ctx: ToolContext) -> list[ToolResult]:
        """Run each planned tool call. Never raises; failures become
        ToolResult(status=ERROR | REFUSED_NEED_AUTH) so synthesis
        gets a uniform shape to read."""
        results: list[ToolResult] = []
        for tc in calls:
            tool = registry.get(tc.name)

            # Router asked for a tool we don't know — log + record
            # as ERROR. The synthesis prompt mentions "if a tool
            # was missing, acknowledge the gap."
            if tool is None:
                results.append(ToolResult(
                    tool_name=tc.name, status=ToolStatus.ERROR,
                    error=f"unknown tool: {tc.name!r}",
                ))
                continue

            # Auth gate — short-circuit instead of letting the tool
            # body do it (cleaner separation, and the auth-refusal
            # message stays consistent across tools).
            if tool.requires_user and ctx.user is None:
                results.append(ToolResult(
                    tool_name=tc.name,
                    status=ToolStatus.REFUSED_NEED_AUTH,
                    error="anonymous_user",
                ))
                continue

            # Arg validation — the router occasionally hallucinates
            # malformed args. Cleaner to fail at the boundary than
            # to defend in every tool body.
            cleaned, err = coerce_args(tool, tc.args)
            if err:
                results.append(ToolResult(
                    tool_name=tc.name, status=ToolStatus.ERROR,
                    error=err,
                ))
                continue

            # Tool execution. Tools are contractually no-raise; this
            # try/except is belt-and-braces against future tools
            # forgetting that contract.
            try:
                results.append(tool.execute(ctx, cleaned))
            except Exception as e:           # pragma: no cover — guard
                log.exception("agentic.tool_raised", extra={"tool": tc.name})
                results.append(ToolResult(
                    tool_name=tc.name, status=ToolStatus.ERROR,
                    error=f"tool raised: {e}",
                ))
        return results

    def _build_history(self, request: AssistantRequest) -> list[dict]:
        history = [{"role": m.role, "content": m.content}
                   for m in request.history]
        history.append({"role": "user", "content": request.message})
        return history

    @staticmethod
    def _append_tool_round_to_messages(
        base_messages: list[dict],
        calls: list[ToolCall],
        results: list[ToolResult],
        router_text: str,
    ) -> list[dict]:
        """Build the message list for a re-plan router call.

        OpenAI's tool-calling protocol requires:

          1. The base conversation messages (system + user history).
          2. An ``assistant`` message that emitted the tool_calls
             (with id, type='function', function.{name,arguments}).
          3. One ``tool`` role message per tool call, keyed by
             tool_call_id, content = the tool's textual output.

        On a re-plan, the router LLM reads this and decides:
          * Try different tools (likely if iter-1 returned empty)
          * Call no tools and answer directly (likely if iter-1
            returned an auth-refusal or error and the model decides
            to ask the user to sign in)

        Anthropic's tool-use format is structurally similar — we'd
        translate at provider boundary in a future Anthropic
        implementation; this helper produces the OpenAI shape.
        """
        # ``arguments`` is JSON-encoded text in OpenAI's format, not
        # a dict. We serialise the args back to JSON for protocol
        # fidelity (the model is happier with a real assistant turn
        # than with our simplified internal shape).
        import json
        assistant_msg = {
            "role": "assistant",
            "content": router_text or None,
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.name,
                        "arguments": json.dumps(c.args),
                    },
                }
                for c in calls
            ],
        }

        # Map results back to their tool_call by ID. The orchestrator
        # builds results in the same order as `calls`, so a positional
        # zip is reliable. The explicit id-pairing makes the resulting
        # messages self-consistent if calls/results ever diverge.
        result_msgs: list[dict] = []
        for c, r in zip(calls, results):
            # Tool content cap matches the synthesis evidence cap so
            # a verbose tool can't blow out the router's context
            # window on re-plan.
            body = (r.content or "").strip()
            if r.status is ToolStatus.EMPTY:
                body = body or "(no relevant content)"
            elif r.status is ToolStatus.ERROR:
                body = f"(tool failed: {r.error or 'unknown'})"
            elif r.status is ToolStatus.REFUSED_NEED_AUTH:
                body = "(tool requires authenticated user; user is anonymous)"
            body = body[:_MAX_TOOL_CONTENT_CHARS]
            result_msgs.append({
                "role": "tool",
                "tool_call_id": c.id,
                "content": body,
            })

        return base_messages + [assistant_msg] + result_msgs

    def _router_system_prompt(self) -> str:
        configured = settings_store.get_str(
            "assistant.agentic.router_system", "")
        return configured.strip() or DEFAULT_ROUTER_SYSTEM

    def _synthesis_system_prompt(
        self, results: list[ToolResult]) -> str:
        configured = settings_store.get_str(
            "assistant.agentic.synthesis_system", "")
        base = configured.strip() or DEFAULT_SYNTHESIS_SYSTEM
        evidence = _format_evidence(results)
        return f"{base}\n\n{evidence}"


# ============================================================ formatting

def _format_evidence(results: list[ToolResult]) -> str:
    """Render tool results as an evidence block the synthesis LLM
    can read. Each result is delimited so the model knows where one
    tool's output ends and the next begins; status is surfaced so
    the model can mention "no data available from X" honestly.

    Sources from RAG tools (faq_search / content_search /
    pricing_lookup) already contain [Source N] markers from the
    handler_support.build_context_block helper. The synthesis
    prompt is instructed to cite using those same numbers; this
    keeps the user-facing citation chips and the LLM's [Source N]
    references consistent.
    """
    if not results:
        return "Evidence: (no tools were called)"

    parts: list[str] = ["Evidence collected from tools:\n"]
    for r in results:
        header = f"--- Tool: {r.tool_name} ({r.status.value}) ---"
        body = r.content[:_MAX_TOOL_CONTENT_CHARS] if r.content else ""
        if r.status is ToolStatus.EMPTY:
            body = body or "(no relevant content found)"
        elif r.status is ToolStatus.ERROR:
            body = f"(tool failed: {r.error or 'unknown error'})"
        elif r.status is ToolStatus.REFUSED_NEED_AUTH:
            body = ("(tool requires the user to be signed in; "
                     "they currently are not)")
        parts.append(header)
        parts.append(body)
        parts.append("")    # blank line separator
    return "\n".join(parts).rstrip()


def _summarise_tool_calls(results: list[ToolResult]) -> list[dict]:
    """One-line per call for the audit log + drift dashboard.
    Excludes full content to keep audit rows small."""
    out: list[dict] = []
    for r in results:
        out.append({
            "name":   r.tool_name,
            "status": r.status.value,
            **({"error": r.error} if r.error else {}),
            **({"metadata": r.metadata} if r.metadata else {}),
        })
    return out


def _ms_since(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


# ---------------------------------------------- user-facing strings

# Shown when the router itself throws. Friendly + non-technical;
# user is invited to retry. Same wording the legacy orchestrator
# uses for its handler crash path so the UX is consistent across
# flows.
_FRIENDLY_ERROR_MESSAGE = (
    "Sorry, I hit an error answering that. Please try again — "
    "if it keeps happening, ask for human follow-up from the chat."
)

# Shown when router or synthesis returns an empty string. Rare
# but possible (provider hiccups, over-strict guardrails). Same
# class of user signal as the drift detector's "empty_response"
# event — we'd rather show this than a blank bubble.
_FRIENDLY_NO_ANSWER = (
    "I'm not sure how to answer that — could you rephrase, or "
    "ask for a human if it's important?"
)
