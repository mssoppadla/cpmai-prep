"""Agentic orchestrator — router → tool exec → synthesis.

V1 is a simple linear state machine in plain Python, NOT LangGraph.
The graph today only has three nodes (router → tools → synthesis)
with no conditional branching or loops — LangGraph's value would be
mostly boilerplate. When we add re-planning (router gets another
shot after empty tool results) we can adopt LangGraph if its
graph-runtime ergonomics start paying off; until then a 100-line
function is easier to test and easier to debug.

Flow for one chat turn::

  ┌─────────────────────────────────────────────────────────┐
  │ 1. Build router system prompt (admin-tunable + tools[]) │
  │ 2. Call provider.complete_with_tools()                  │ ← LLM #1 (router)
  │ 3. If router emitted NO tool_calls:                     │
  │       → return router's text as the answer (no LLM #2)  │
  │    Else:                                                │
  │ 4.    Execute each tool_call:                           │
  │         - registry.get(name) — unknown name = error     │
  │         - check requires_user — refuse if anon          │
  │         - coerce_args via JSON-schema                   │
  │         - tool.execute(ctx, args) — never raises        │
  │ 5.    Build synthesis system prompt with tool results   │
  │       as evidence + admin guardrail preamble            │
  │ 6.    Call provider.complete()                          │ ← LLM #2 (synthesis)
  │ 7.    Aggregate citations + suggested_actions from      │
  │       OK tool results                                   │
  │ 8.    Return final AgenticResult                        │
  └─────────────────────────────────────────────────────────┘

What this PR INTENTIONALLY does NOT include (deferred):

  * **Re-planning** — when every tool returned EMPTY/ERROR, the
    router gets a second shot with the new evidence in context.
    Bounded by ``assistant.agentic.tools_max_calls``. V1 caps at
    a single router pass; if re-plan turns out to be necessary in
    observation, it's a few lines + one more LLM call.
  * **Multi-turn tool chaining** — the OpenAI tool-calling protocol
    supports an arbitrary chain (assistant → tools → assistant →
    tools → ...). V1 does one round of tools + one round of
    synthesis. Same justification.
  * **Shadow mode** — when ``assistant.flow=shadow`` the resolver
    asks for both legacy + agentic to run. The wiring to run the
    agentic side in the background lives in the main orchestrator
    (next step), not here. This module just answers "given that
    you've decided to run agentic, here's the result".
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

        # -------- Step 1+2: Router call -----------------------------
        router_system = with_preamble(self._router_system_prompt())
        try:
            router_resp = self.provider.complete_with_tools(
                router_system, history, tools=tools_schema,
            )
        except Exception as e:
            log.exception("agentic.router_failed")
            return AgenticResult(
                message=_FRIENDLY_ERROR_MESSAGE,
                error=f"router_failed: {e}",
                metadata={"phase": "router", "elapsed_ms": _ms_since(started)},
            )

        # -------- Step 3: No tools → router answered directly --------
        if not router_resp.tool_calls:
            return AgenticResult(
                message=router_resp.text.strip() or _FRIENDLY_NO_ANSWER,
                tools_called=[],
                metadata={
                    "phase": "router_only",
                    "elapsed_ms": _ms_since(started),
                    "finish_reason": router_resp.finish_reason,
                },
            )

        # -------- Step 4: Execute tools ------------------------------
        max_calls = max(1, settings_store.get_int(
            "assistant.agentic.tools_max_calls", 4))
        # Trim if the router emitted more calls than the cap — usually
        # 1-2 in practice, but defensive against a runaway response.
        planned = router_resp.tool_calls[:max_calls]
        results = self._execute_tools(planned, ctx)

        # -------- Step 5+6: Synthesis --------------------------------
        synth_system = with_preamble(
            self._synthesis_system_prompt(results))
        try:
            answer = self.provider.complete(synth_system, history)
        except Exception as e:
            log.exception("agentic.synthesis_failed")
            return AgenticResult(
                message=_FRIENDLY_ERROR_MESSAGE,
                tools_called=_summarise_tool_calls(results),
                error=f"synthesis_failed: {e}",
                metadata={"phase": "synthesis", "elapsed_ms": _ms_since(started)},
            )

        # -------- Step 7: Aggregate citations + actions --------------
        citations: list[dict] = []
        suggested_actions: list[dict] = []
        for r in results:
            if r.status is ToolStatus.OK:
                citations.extend(r.citations)
                suggested_actions.extend(r.suggested_actions)

        return AgenticResult(
            message=answer.strip() or _FRIENDLY_NO_ANSWER,
            citations=citations,
            suggested_actions=suggested_actions,
            tools_called=_summarise_tool_calls(results),
            metadata={
                "phase": "synthesis",
                "elapsed_ms": _ms_since(started),
                "tools_planned": len(router_resp.tool_calls),
                "tools_executed": len(results),
                "tools_ok":     sum(1 for r in results if r.status is ToolStatus.OK),
                "tools_empty":  sum(1 for r in results if r.status is ToolStatus.EMPTY),
                "tools_error":  sum(1 for r in results if r.status is ToolStatus.ERROR),
                "tools_refused_need_auth":
                    sum(1 for r in results
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
