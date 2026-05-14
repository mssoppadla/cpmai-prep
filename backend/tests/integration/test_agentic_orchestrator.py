"""End-to-end tests for the agentic orchestrator.

These tests drive ``AgenticOrchestrator.handle`` with a FakeProvider
whose tool-call decisions are scripted, so we exercise the full
state machine (router → tools → synthesis) deterministically.

Coverage:

  * Router picks 1 tool → that tool runs → synthesis answers
  * Router picks 2 tools → both run → synthesis combines results
  * Router picks 0 tools (conversational turn) → router's text
    is the answer; synthesis is NOT called
  * Router picks an unknown tool name → result reports ERROR;
    synthesis sees the failure in evidence and answers honestly
  * Router asks for an auth-required tool while anonymous →
    result reports REFUSED_NEED_AUTH; synthesis prompts sign-in
  * Router emits malformed args (missing required) → result
    reports ERROR; tool body is never called
  * Provider raises during router → result has friendly error,
    no synthesis call
  * Provider raises during synthesis → result has friendly error,
    tools were still executed (state preserved in metadata)
  * Citations + suggested_actions from OK tools are aggregated
    onto the final result
  * tools_max_calls cap trims extra calls (router won't run amok)

The FakeProvider records EVERY ``complete`` and ``complete_with_tools``
invocation so assertions can verify "router was called once, synth
was called once, in that order". Tests are independent — fixture
resets the provider state per test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from unittest.mock import patch

import pytest

from app.schemas.assistant import AssistantRequest
from app.services.assistant.agentic.orchestrator import (
    AgenticOrchestrator, AgenticResult,
)
from app.services.assistant.agentic.types import (
    ToolResult, ToolStatus,
)
from app.services.assistant.providers.base import (
    LLMProvider, ToolCall, ToolCallingResponse,
)
from app.services.assistant.rag.retrieve import RetrievedChunk


# ============================================================ FakeProvider

@dataclass
class _Call:
    """One recorded call to the FakeProvider — kind, system text,
    history. Tests assert on the sequence of these."""
    kind:     str                   # "complete" or "complete_with_tools"
    system:   str
    messages: list[dict]
    tools:    list[dict] | None = None


class FakeProvider(LLMProvider):
    """Deterministic LLM provider for testing.

    Plug a ``router_response`` (returned from complete_with_tools)
    and a ``synthesis_text`` (returned from complete) at construction
    time. Records every call for assertion.

    Both response slots accept either a value OR a callable. Callable
    form is invoked with the call's (system, messages) and lets a
    test return different responses based on what the caller sent
    (e.g., to simulate re-plan scenarios in a future PR).
    """
    name = "fake"

    def __init__(
        self,
        router_response: ToolCallingResponse | Callable | None = None,
        synthesis_text: str | Callable | None = None,
        model: str = "fake-v1",
    ):
        self.model = model
        self.router_response = router_response or ToolCallingResponse(
            text="(no router response configured)", tool_calls=[],
        )
        self.synthesis_text = synthesis_text or "(no synthesis configured)"
        self.calls: list[_Call] = []
        self.complete_raises: Exception | None = None
        self.complete_with_tools_raises: Exception | None = None

    def complete(self, system: str, messages: list[dict], **kwargs) -> str:
        self.calls.append(_Call("complete", system, list(messages)))
        if self.complete_raises:
            raise self.complete_raises
        if callable(self.synthesis_text):
            return self.synthesis_text(system, messages)
        return self.synthesis_text

    def complete_with_tools(
        self, system: str, messages: list[dict], tools: list[dict], **kwargs,
    ) -> ToolCallingResponse:
        self.calls.append(_Call(
            "complete_with_tools", system, list(messages), list(tools),
        ))
        if self.complete_with_tools_raises:
            raise self.complete_with_tools_raises
        if callable(self.router_response):
            return self.router_response(system, messages)
        return self.router_response


# ============================================================ helpers

def _req(message: str = "Tell me about CPMAI fees", anon: str = "test-anon"):
    """Build an AssistantRequest with no prior history."""
    return AssistantRequest(message=message, history=[], anon_id=anon)


def _tc(name: str, args: dict | None = None, id: str = "call_1") -> ToolCall:
    """Shorthand for building a ToolCall the FakeProvider returns."""
    return ToolCall(id=id, name=name, args=args or {})


def _chunk(content: str = "some context", source_type: str = "upload"):
    return RetrievedChunk(
        chunk_id=1, source_type=source_type, source_id="s",
        content=content, similarity=0.6, metadata={},
    )


# RAG tools call retrieve_context inside their respective modules;
# patch at the importer's binding.
def _patch_rag(chunks: list[RetrievedChunk] | None = None):
    chunks = chunks if chunks is not None else [_chunk()]
    return [
        patch(f"app.services.assistant.agentic.tools.{m}.retrieve_context",
               return_value=chunks)
        for m in ("faq_search", "content_search", "pricing_lookup")
    ]


# ============================================================ tests

class TestAgenticOrchestratorRouterPicksOneTool:
    """Happy path: router picks one RAG tool, tool returns chunks,
    synthesis combines into an answer with citations."""

    def test_router_picks_faq_search_synthesis_answers_with_citations(
        self, db,
    ):
        fake = FakeProvider(
            router_response=ToolCallingResponse(
                text="",
                tool_calls=[_tc("faq_search", {"query": "exam fee"})],
                finish_reason="tool_calls",
            ),
            synthesis_text="The exam fee is documented [Source 1].",
        )
        orch = AgenticOrchestrator(db, fake)
        with _patch_rag([_chunk("Exam fee is $500.")])[0]:
            result = orch.handle(_req(), user=None, anon_id="anon-x")

        # Router was called, then synthesis was called — in that order.
        assert [c.kind for c in fake.calls] == [
            "complete_with_tools", "complete",
        ]
        assert result.message == "The exam fee is documented [Source 1]."
        # Citations passed through from the tool's RetrievedChunk.
        assert len(result.citations) == 1
        # Tool call summary captures the OK status. Metadata gets the
        # tool's own keys (chunks_returned etc.) PLUS the orchestrator-
        # added ``tool_elapsed_ms``; assert per-key instead of exact-
        # match to keep the test robust against future telemetry adds.
        assert len(result.tools_called) == 1
        tc = result.tools_called[0]
        assert tc["name"] == "faq_search"
        assert tc["status"] == "ok"
        assert tc["metadata"]["chunks_returned"] == 1
        assert tc["metadata"]["top_similarity"] == 0.6
        assert tc["metadata"]["query"] == "exam fee"
        # Latency stamp added by the orchestrator — int, >= 0.
        assert isinstance(tc["metadata"]["tool_elapsed_ms"], int)
        assert tc["metadata"]["tool_elapsed_ms"] >= 0
        # Metadata records the phase + counts so the future drift
        # dashboard can show "1/1 OK".
        assert result.metadata["phase"] == "synthesis"
        assert result.metadata["tools_ok"] == 1


class TestAgenticOrchestratorMultiTool:
    """Multi-topic question: router picks 2 tools, both run,
    synthesis combines."""

    def test_two_tools_run_in_order_citations_aggregated(self, db):
        fake = FakeProvider(
            router_response=ToolCallingResponse(
                text="",
                tool_calls=[
                    _tc("content_search", {"query": "deployment phase"},
                         id="c1"),
                    _tc("pricing_lookup", {"query": "exam bundle"},
                         id="c2"),
                ],
                finish_reason="tool_calls",
            ),
            synthesis_text=(
                "Deployment phase covers… [Source 1]. The bundle "
                "costs… [Source 2]."
            ),
        )
        orch = AgenticOrchestrator(db, fake)
        with _patch_rag([_chunk("Deployment phase content")])[1], \
             _patch_rag([_chunk("Bundle price content",
                                 source_type="plan")])[2]:
            result = orch.handle(_req(), user=None, anon_id="anon-x")

        # Citations from BOTH tools land on the final result.
        assert len(result.citations) == 2
        # Pricing tool always emits the "View pricing" CTA.
        labels = [a["label"] for a in result.suggested_actions]
        assert "View pricing" in labels
        # Both tool-call summaries recorded.
        names = {t["name"] for t in result.tools_called}
        assert names == {"content_search", "pricing_lookup"}
        assert result.metadata["tools_ok"] == 2


class TestAgenticOrchestratorNoToolsRouted:
    """Conversational turn: router emits NO tool_calls. Router's text
    is the answer; no synthesis call happens (one LLM call total)."""

    def test_router_only_no_synthesis_call(self, db):
        fake = FakeProvider(
            router_response=ToolCallingResponse(
                text="Hi! Ask me about CPMAI anytime.",
                tool_calls=[],
                finish_reason="stop",
            ),
            synthesis_text="(should not be called)",
        )
        orch = AgenticOrchestrator(db, fake)
        result = orch.handle(_req("Hi"), user=None, anon_id="anon-x")

        # Only router was called — synthesis was never invoked.
        assert [c.kind for c in fake.calls] == ["complete_with_tools"]
        assert result.message == "Hi! Ask me about CPMAI anytime."
        assert result.tools_called == []
        assert result.metadata["phase"] == "router_only"

    def test_router_empty_text_falls_back_to_friendly_message(self, db):
        """Provider returned tool_calls=[] AND empty text. Don't
        show a blank bubble — friendly fallback wording."""
        fake = FakeProvider(
            router_response=ToolCallingResponse(
                text="", tool_calls=[], finish_reason="stop"),
        )
        orch = AgenticOrchestrator(db, fake)
        result = orch.handle(_req(), user=None, anon_id="anon-x")
        assert result.message    # non-empty
        assert "rephrase" in result.message.lower() or "not sure" in result.message.lower()


class TestAgenticOrchestratorUnknownTool:
    """Router hallucinates a tool name that doesn't exist."""

    def test_unknown_tool_recorded_as_error_synth_still_runs(self, db):
        fake = FakeProvider(
            router_response=ToolCallingResponse(
                text="",
                tool_calls=[_tc("teleport_user", {})],
                finish_reason="tool_calls",
            ),
            synthesis_text="I don't have the right tool for that.",
        )
        orch = AgenticOrchestrator(db, fake)
        result = orch.handle(_req(), user=None, anon_id="anon-x")

        # Synthesis still runs — the prompt instructs it to admit
        # the gap honestly.
        assert [c.kind for c in fake.calls] == [
            "complete_with_tools", "complete",
        ]
        assert result.tools_called == [{
            "name": "teleport_user",
            "status": "error",
            "error": "unknown tool: 'teleport_user'",
        }]


class TestAgenticOrchestratorAuthRequired:
    """Router picks an auth-required tool while user is anonymous."""

    def test_anon_calling_account_state_refused(self, db):
        fake = FakeProvider(
            router_response=ToolCallingResponse(
                text="",
                tool_calls=[_tc("account_state", {})],
                finish_reason="tool_calls",
            ),
            synthesis_text=(
                "Please sign in so I can look up your subscription."
            ),
        )
        orch = AgenticOrchestrator(db, fake)
        result = orch.handle(_req(), user=None, anon_id="anon-x")

        assert result.tools_called[0]["status"] == "refused_need_auth"
        assert result.metadata["tools_refused_need_auth"] == 1
        # Tool body never ran — orchestrator short-circuited at the
        # gate. (Verified implicitly: if it had run, the DB-less
        # ToolContext would have raised; the test would error.)


class TestAgenticOrchestratorMalformedArgs:
    """Router omits a required arg."""

    def test_missing_required_arg_recorded_as_error(self, db):
        fake = FakeProvider(
            router_response=ToolCallingResponse(
                text="",
                # faq_search requires "query"; we pass nothing.
                tool_calls=[_tc("faq_search", {})],
                finish_reason="tool_calls",
            ),
            synthesis_text="I couldn't form a search query.",
        )
        orch = AgenticOrchestrator(db, fake)
        result = orch.handle(_req(), user=None, anon_id="anon-x")

        assert result.tools_called[0]["status"] == "error"
        assert "missing required" in result.tools_called[0]["error"]


class TestAgenticOrchestratorProviderFailure:
    """Provider raises during router or synthesis."""

    def test_router_failure_friendly_error_no_synthesis(self, db):
        fake = FakeProvider()
        fake.complete_with_tools_raises = RuntimeError("rate limited")
        orch = AgenticOrchestrator(db, fake)
        result = orch.handle(_req(), user=None, anon_id="anon-x")
        # Synthesis was NOT called (we never got past the router).
        assert [c.kind for c in fake.calls] == ["complete_with_tools"]
        assert "error" in result.message.lower()
        assert "router_failed" in (result.error or "")
        assert result.metadata["phase"] == "router"

    def test_synthesis_failure_friendly_error_tools_preserved(self, db):
        fake = FakeProvider(
            router_response=ToolCallingResponse(
                text="",
                tool_calls=[_tc("faq_search", {"query": "x"})],
                finish_reason="tool_calls",
            ),
        )
        fake.complete_raises = RuntimeError("synth boom")
        orch = AgenticOrchestrator(db, fake)
        with _patch_rag()[0]:
            result = orch.handle(_req(), user=None, anon_id="anon-x")
        assert "synthesis_failed" in (result.error or "")
        # Tool ran successfully before synth failed — preserved
        # in tools_called for the audit log.
        assert result.tools_called[0]["status"] == "ok"


class TestAgenticOrchestratorMaxCallsCap:
    """Router emits more tool_calls than tools_max_calls; extras
    are trimmed."""

    def test_extra_calls_trimmed_at_cap(self, db):
        from app.core.settings_store import settings_store

        # Lower the cap to 2 so we can construct a controlled
        # 3-call scenario.
        with patch.object(settings_store, "get_int",
                           side_effect=lambda k, d=0:
                               2 if k == "assistant.agentic.tools_max_calls"
                               else d):
            fake = FakeProvider(
                router_response=ToolCallingResponse(
                    text="",
                    tool_calls=[
                        _tc("faq_search", {"query": "a"}, id="1"),
                        _tc("content_search", {"query": "b"}, id="2"),
                        _tc("pricing_lookup", {"query": "c"}, id="3"),
                    ],
                ),
                synthesis_text="x",
            )
            orch = AgenticOrchestrator(db, fake)
            with _patch_rag()[0], _patch_rag()[1], _patch_rag()[2]:
                result = orch.handle(_req(), user=None, anon_id="anon-x")

        # Only the first 2 were executed.
        assert len(result.tools_called) == 2
        assert result.metadata["tools_planned"] == 3
        assert result.metadata["tools_executed"] == 2


class TestAgenticOrchestratorReplan:
    """Re-plan behaviour — when iteration 1 returns only EMPTY
    results (no OK, no actionable ERROR/auth-refusal), the router
    gets one more shot with the prior tool outputs in context.

    All other failure modes (ERROR-only, auth-only, mixed-with-OK)
    do NOT trigger re-plan — those are either non-recoverable or
    already have evidence."""

    def _two_response_provider(
        self, first: ToolCallingResponse, second: ToolCallingResponse,
        synth_text: str = "synth answer",
    ) -> FakeProvider:
        """Build a FakeProvider that returns ``first`` on the first
        complete_with_tools call and ``second`` on subsequent calls.

        The callable router_response form lets us simulate a router
        that re-plans differently after seeing tool results."""
        state = {"call_count": 0}

        def script(system, messages):
            state["call_count"] += 1
            return first if state["call_count"] == 1 else second

        return FakeProvider(router_response=script,
                             synthesis_text=synth_text)

    def test_replan_fires_when_iter1_all_empty(self, db):
        """Iter 1: faq_search returns EMPTY. Re-plan fires.
        Iter 2: content_search picks different tool, returns chunks.
        Synthesis runs on iter-2 evidence."""
        fake = self._two_response_provider(
            first=ToolCallingResponse(
                text="", finish_reason="tool_calls",
                tool_calls=[_tc("faq_search", {"query": "x"}, id="1")],
            ),
            second=ToolCallingResponse(
                text="", finish_reason="tool_calls",
                tool_calls=[_tc("content_search", {"query": "x"}, id="2")],
            ),
            synth_text="grounded answer from re-plan",
        )
        orch = AgenticOrchestrator(db, fake)
        with patch(
            "app.services.assistant.agentic.tools.faq_search.retrieve_context",
            return_value=[],   # iter 1 → EMPTY
        ), patch(
            "app.services.assistant.agentic.tools.content_search.retrieve_context",
            return_value=[_chunk("found this on re-plan")],  # iter 2 → OK
        ):
            result = orch.handle(_req(), user=None, anon_id="anon-x")

        # Two router calls + one synthesis = three total LLM calls.
        kinds = [c.kind for c in fake.calls]
        assert kinds == [
            "complete_with_tools", "complete_with_tools", "complete",
        ]
        assert result.metadata["replans_fired"] == 1
        # Both tools were executed (iter 1 empty + iter 2 ok).
        names = [t["name"] for t in result.tools_called]
        assert names == ["faq_search", "content_search"]
        # Citations come from iter-2 OK result.
        assert len(result.citations) == 1
        assert result.metadata["tools_empty"] == 1
        assert result.metadata["tools_ok"] == 1

    def test_replan_skipped_when_iter1_has_ok_result(self, db):
        """If iter 1 returns ANY ok result, don't waste a router
        call on re-plan — synthesis has evidence to work with."""
        called_second_router = {"flag": False}

        def script(system, messages):
            if called_second_router["flag"]:
                # If this fires, test should fail loudly.
                raise AssertionError(
                    "second router call should NOT happen — iter 1 had OK")
            called_second_router["flag"] = True
            return ToolCallingResponse(
                text="", finish_reason="tool_calls",
                tool_calls=[_tc("faq_search", {"query": "x"})],
            )

        fake = FakeProvider(router_response=script,
                             synthesis_text="answer")
        orch = AgenticOrchestrator(db, fake)
        with patch(
            "app.services.assistant.agentic.tools.faq_search.retrieve_context",
            return_value=[_chunk("good content")],  # OK
        ):
            result = orch.handle(_req(), user=None, anon_id="anon-x")

        assert result.metadata["replans_fired"] == 0
        # Single router + single synth = 2 calls only.
        assert len(fake.calls) == 2

    def test_replan_skipped_when_all_error(self, db):
        """ERROR-only results are not fixable by re-planning with the
        same prompt — synthesis frames the error to the user instead."""
        fake = self._two_response_provider(
            # Iter 1: malformed args → ERROR
            first=ToolCallingResponse(
                text="", finish_reason="tool_calls",
                tool_calls=[_tc("faq_search", {}, id="1")],  # missing query
            ),
            # Iter 2 won't fire — but if it did, we'd catch it here.
            second=ToolCallingResponse(
                text="", finish_reason="stop", tool_calls=[],
            ),
        )
        orch = AgenticOrchestrator(db, fake)
        result = orch.handle(_req(), user=None, anon_id="anon-x")

        assert result.metadata["replans_fired"] == 0
        # Only one router call.
        assert sum(1 for c in fake.calls if c.kind == "complete_with_tools") == 1

    def test_replan_skipped_when_only_auth_refused(self, db):
        """REFUSED_NEED_AUTH means the user is anonymous. Re-planning
        won't change that — synthesis asks them to sign in."""
        fake = self._two_response_provider(
            first=ToolCallingResponse(
                text="", finish_reason="tool_calls",
                tool_calls=[_tc("account_state", {}, id="1")],
            ),
            second=ToolCallingResponse(
                text="should not fire", finish_reason="stop", tool_calls=[],
            ),
        )
        orch = AgenticOrchestrator(db, fake)
        result = orch.handle(_req(), user=None, anon_id="anon-x")

        assert result.metadata["replans_fired"] == 0
        assert sum(1 for c in fake.calls if c.kind == "complete_with_tools") == 1

    def test_replan_blocked_when_budget_exhausted(self, db):
        """Iter 1 uses all 4 tool slots; even though they all return
        EMPTY, re-plan can't fire — cost guard."""
        from app.core.settings_store import settings_store

        with patch.object(settings_store, "get_int",
                           side_effect=lambda k, d=0:
                               4 if k == "assistant.agentic.tools_max_calls"
                               else d):
            fake = self._two_response_provider(
                first=ToolCallingResponse(
                    text="", finish_reason="tool_calls",
                    tool_calls=[
                        _tc("faq_search", {"query": "a"}, id="1"),
                        _tc("content_search", {"query": "b"}, id="2"),
                        _tc("pricing_lookup", {"query": "c"}, id="3"),
                        _tc("faq_search", {"query": "d"}, id="4"),
                    ],
                ),
                second=ToolCallingResponse(
                    text="should not fire", finish_reason="stop",
                    tool_calls=[],
                ),
            )
            orch = AgenticOrchestrator(db, fake)
            with patch(
                "app.services.assistant.agentic.tools.faq_search.retrieve_context",
                return_value=[],
            ), patch(
                "app.services.assistant.agentic.tools.content_search.retrieve_context",
                return_value=[],
            ), patch(
                "app.services.assistant.agentic.tools.pricing_lookup.retrieve_context",
                return_value=[],
            ):
                result = orch.handle(_req(), user=None, anon_id="anon-x")

        # Budget = 4, iter 1 used all 4 → no re-plan possible.
        assert result.metadata["replans_fired"] == 0
        assert sum(1 for c in fake.calls if c.kind == "complete_with_tools") == 1

    def test_replan_router_emits_no_tools_on_second_pass(self, db):
        """Re-plan fires but the router decides not to call any tools
        on its second pass (it gives up). Synthesis still runs on
        iter-1 evidence."""
        fake = self._two_response_provider(
            first=ToolCallingResponse(
                text="", finish_reason="tool_calls",
                tool_calls=[_tc("faq_search", {"query": "x"}, id="1")],
            ),
            # Re-plan returns no tools — router decided to give up.
            second=ToolCallingResponse(
                text="(router gave up)", finish_reason="stop",
                tool_calls=[],
            ),
        )
        orch = AgenticOrchestrator(db, fake)
        with patch(
            "app.services.assistant.agentic.tools.faq_search.retrieve_context",
            return_value=[],
        ):
            result = orch.handle(_req(), user=None, anon_id="anon-x")

        # Two router calls (iter 1 + re-plan), then synthesis.
        kinds = [c.kind for c in fake.calls]
        assert kinds == [
            "complete_with_tools", "complete_with_tools", "complete",
        ]
        assert result.metadata["replans_fired"] == 1
        # Only iter-1's tool was executed.
        assert len(result.tools_called) == 1
        assert result.tools_called[0]["name"] == "faq_search"

    def test_replan_failure_does_not_crash_turn(self, db):
        """If the second router call raises (rate-limit, network),
        the turn still completes — synthesis runs on iter-1 results
        and result.error reports replan_failed."""
        attempt = {"n": 0}

        def script(system, messages):
            attempt["n"] += 1
            if attempt["n"] == 1:
                return ToolCallingResponse(
                    text="", finish_reason="tool_calls",
                    tool_calls=[_tc("faq_search", {"query": "x"}, id="1")],
                )
            raise RuntimeError("rate limit on re-plan")

        fake = FakeProvider(router_response=script,
                             synthesis_text="synth on iter-1")
        orch = AgenticOrchestrator(db, fake)
        with patch(
            "app.services.assistant.agentic.tools.faq_search.retrieve_context",
            return_value=[],
        ):
            result = orch.handle(_req(), user=None, anon_id="anon-x")

        assert result.metadata["replans_fired"] == 1
        assert "replan_failed" in (result.error or "")
        # Synthesis still ran.
        assert "synth on iter-1" in result.message

    def test_replan_messages_include_prior_tool_round(self, db):
        """The re-plan router call must receive the iter-1
        assistant-tool-call message + tool result message so it has
        evidence to decide differently. Pin the message protocol."""
        observed_messages: list[list[dict]] = []

        def script(system, messages):
            observed_messages.append(list(messages))
            if len(observed_messages) == 1:
                return ToolCallingResponse(
                    text="", finish_reason="tool_calls",
                    tool_calls=[_tc("faq_search", {"query": "x"}, id="abc")],
                )
            return ToolCallingResponse(
                text="", finish_reason="stop", tool_calls=[])

        fake = FakeProvider(router_response=script, synthesis_text="x")
        orch = AgenticOrchestrator(db, fake)
        with patch(
            "app.services.assistant.agentic.tools.faq_search.retrieve_context",
            return_value=[],   # EMPTY → re-plan
        ):
            orch.handle(_req(), user=None, anon_id="anon-x")

        # Second call should have prior tool round appended.
        assert len(observed_messages) == 2
        iter2 = observed_messages[1]
        # Find the assistant message with tool_calls.
        asst = [m for m in iter2
                 if m.get("role") == "assistant" and m.get("tool_calls")]
        assert len(asst) == 1
        assert asst[0]["tool_calls"][0]["function"]["name"] == "faq_search"
        # Tool result message with matching tool_call_id.
        tool_msgs = [m for m in iter2 if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "abc"


class TestAgenticOrchestratorPromptComposition:
    """The synthesis system prompt should include the evidence block
    and pass through the admin-configured preamble."""

    def test_synthesis_prompt_includes_evidence_block(self, db):
        fake = FakeProvider(
            router_response=ToolCallingResponse(
                text="",
                tool_calls=[_tc("faq_search", {"query": "x"})],
                finish_reason="tool_calls",
            ),
            synthesis_text="answer",
        )
        orch = AgenticOrchestrator(db, fake)
        with _patch_rag([_chunk("SPECIAL_MARKER_42")])[0]:
            orch.handle(_req(), user=None, anon_id="anon-x")
        # The second call (synthesis) must have the chunk content
        # in its system prompt.
        synth_call = fake.calls[1]
        assert synth_call.kind == "complete"
        assert "SPECIAL_MARKER_42" in synth_call.system
        # And evidence-block marker the orchestrator inserts.
        assert "--- Tool: faq_search" in synth_call.system
