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
        # Tool call summary captures the OK status.
        assert result.tools_called == [{
            "name": "faq_search",
            "status": "ok",
            "metadata": {
                "chunks_returned": 1,
                "top_similarity": 0.6,
                "query": "exam fee",
            },
        }]
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
