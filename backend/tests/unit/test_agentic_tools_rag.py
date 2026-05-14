"""Tests for the three RAG-based agentic tools.

These tools (faq_search, content_search, pricing_lookup) are thin
wrappers around the shared ``retrieve_context`` helper plus the
existing prompt-assembly and citation-formatting code that the
legacy handlers already use. The tests below pin:

  * The OUTPUT shape — synthesis (next PR) relies on this
  * The retrieval policy — source_types correct per tool, so a tool
    can't accidentally start returning chunks from the wrong corpus
  * Empty / error handling — tools NEVER raise
  * has_llm_call flag — used by cost accounting later

Retrieval itself is mocked. Real pgvector behaviour is tested in
existing tests/unit/rag/.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.assistant.agentic.tools.content_search import ContentSearchTool
from app.services.assistant.agentic.tools.faq_search import FaqSearchTool
from app.services.assistant.agentic.tools.pricing_lookup import PricingLookupTool
from app.services.assistant.agentic.types import ToolContext, ToolStatus
from app.services.assistant.rag.retrieve import RetrievedChunk


# --------------------------------------------------------------- helpers

def _chunk(*, source_type="upload", content="text", filename=None):
    return RetrievedChunk(
        chunk_id=1, source_type=source_type, source_id="s",
        content=content, similarity=0.7,
        metadata={"filename": filename} if filename else {},
    )


def _ctx():
    """All RAG tools take ToolContext but only touch ``db``. Pass a
    bare object — None is fine as long as retrieval is mocked."""
    return ToolContext(db=None, user=None, anon_id=None)


def _patch_target(module_name: str):
    """Return the dotted patch path for ``retrieve_context`` as
    imported into a given tool module — Python re-binds names at
    import time so we must patch the IMPORTER, not the source."""
    return f"app.services.assistant.agentic.tools.{module_name}.retrieve_context"


# ============================================================ shared shape

@pytest.mark.parametrize("tool_cls", [FaqSearchTool, ContentSearchTool,
                                       PricingLookupTool])
def test_rag_tool_declares_embedding_llm_use(tool_cls):
    """Cost accounting depends on this flag. Don't silently flip it
    to False without thinking about audit-log dashboards."""
    t = tool_cls()
    assert t.has_llm_call is True
    assert t.requires_user is False


@pytest.mark.parametrize("tool_cls, module_name", [
    (FaqSearchTool,     "faq_search"),
    (ContentSearchTool, "content_search"),
    (PricingLookupTool, "pricing_lookup"),
])
def test_rag_tool_returns_error_on_empty_query(tool_cls, module_name):
    """Defensive arg check — synthesis sees status=ERROR rather than
    a "we searched for empty string" no-op."""
    t = tool_cls()
    r = t.execute(_ctx(), {"query": ""})
    assert r.status is ToolStatus.ERROR
    assert "empty" in (r.error or "").lower()


@pytest.mark.parametrize("tool_cls, module_name", [
    (FaqSearchTool,     "faq_search"),
    (ContentSearchTool, "content_search"),
    (PricingLookupTool, "pricing_lookup"),
])
def test_rag_tool_returns_empty_when_no_chunks(tool_cls, module_name):
    """Real, non-error-but-empty case: the retriever ran cleanly,
    returned 0 chunks (below similarity threshold). Status=EMPTY so
    synthesis can decide to either try another tool or to honestly
    say "no relevant info found"."""
    t = tool_cls()
    with patch(_patch_target(module_name), return_value=[]):
        r = t.execute(_ctx(), {"query": "anything"})
    assert r.status is ToolStatus.EMPTY
    assert r.content == ""
    assert r.metadata["chunks_returned"] == 0


@pytest.mark.parametrize("tool_cls, module_name", [
    (FaqSearchTool,     "faq_search"),
    (ContentSearchTool, "content_search"),
    (PricingLookupTool, "pricing_lookup"),
])
def test_rag_tool_returns_ok_with_chunks_and_citations(tool_cls, module_name):
    """Happy path — chunks come back; content has the formatted
    context block; citations match shape; metadata has counts."""
    t = tool_cls()
    chunks = [_chunk(content="Chunk A about CPMAI."),
              _chunk(content="Chunk B about exam.")]
    with patch(_patch_target(module_name), return_value=chunks):
        r = t.execute(_ctx(), {"query": "test"})
    assert r.status is ToolStatus.OK
    assert "[Source 1]" in r.content
    assert "[Source 2]" in r.content
    assert len(r.citations) == 2
    assert r.metadata["chunks_returned"] == 2


@pytest.mark.parametrize("tool_cls, module_name", [
    (FaqSearchTool,     "faq_search"),
    (ContentSearchTool, "content_search"),
    (PricingLookupTool, "pricing_lookup"),
])
def test_rag_tool_does_not_raise_on_retrieval_exception(tool_cls, module_name):
    """A tool exception breaks LangGraph state. We catch + downgrade
    to status=ERROR. (retrieve_context already swallows its own
    errors and returns []; this guards against future refactors.)"""
    t = tool_cls()
    with patch(_patch_target(module_name),
                 side_effect=RuntimeError("pgvector exploded")):
        r = t.execute(_ctx(), {"query": "test"})
    assert r.status is ToolStatus.ERROR
    assert "pgvector exploded" in (r.error or "")


# ============================================================ per-tool retrieval scope

def test_faq_search_targets_faq_plus_upload_corpora():
    """If someone changes the source_types here, they're rerouting
    EVERY agentic FAQ question to a different corpus. Pin it."""
    with patch(_patch_target("faq_search"), return_value=[]) as m:
        FaqSearchTool().execute(_ctx(), {"query": "x"})
    kw = m.call_args.kwargs
    assert "faq" in kw["source_types"]
    assert "upload" in kw["source_types"]


def test_content_search_targets_question_explanation_plus_upload():
    with patch(_patch_target("content_search"), return_value=[]) as m:
        ContentSearchTool().execute(_ctx(), {"query": "x"})
    kw = m.call_args.kwargs
    assert "question_explanation" in kw["source_types"]
    assert "upload" in kw["source_types"]


def test_pricing_lookup_targets_only_plan_corpus():
    """Pricing must NEVER answer from the upload corpus — admin-
    uploaded docs aren't an authoritative pricing source."""
    with patch(_patch_target("pricing_lookup"), return_value=[]) as m:
        PricingLookupTool().execute(_ctx(), {"query": "x"})
    kw = m.call_args.kwargs
    assert list(kw["source_types"]) == ["plan"]


# ============================================================ pricing extra

def test_pricing_lookup_always_includes_view_pricing_action():
    """OK or EMPTY, the pricing-page deep-link is a useful fallback
    affordance. Synthesis is free to pass it through to the user."""
    # EMPTY case
    with patch(_patch_target("pricing_lookup"), return_value=[]):
        r = PricingLookupTool().execute(_ctx(), {"query": "x"})
    assert r.suggested_actions == [{"label": "View pricing", "url": "/pricing"}]

    # OK case
    with patch(_patch_target("pricing_lookup"),
                 return_value=[_chunk(source_type="plan", content="X")]):
        r = PricingLookupTool().execute(_ctx(), {"query": "x"})
    assert r.suggested_actions == [{"label": "View pricing", "url": "/pricing"}]
