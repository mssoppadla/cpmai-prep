"""faq_search tool — RAG retrieval over the FAQ + upload corpora.

Equivalent in retrieval policy to the legacy FAQHandler, minus the
LLM-generation step (synthesis does that once at the end of the
agentic turn, for all tool results combined).

Sources searched:
  * ``faq`` — admin-authored FAQ rows
  * ``upload`` (and any future SHARED_KNOWLEDGE_SOURCES) — admin-
    uploaded reference documents

Cost per call: one embedding call (~$0.00002), no generation.
"""
from __future__ import annotations

from typing import Any

from app.services.assistant.agentic.registry import register
from app.services.assistant.agentic.types import (
    Tool, ToolContext, ToolResult, ToolStatus,
)
from app.services.assistant.rag.handler_support import (
    SHARED_KNOWLEDGE_SOURCES,
    build_context_block, retrieve_context, to_citations,
)


class FaqSearchTool(Tool):
    name = "faq_search"
    description = (
        "Search the CPMAI FAQ and any admin-uploaded reference "
        "documents for content relevant to the user's question. Use "
        "this for factual questions about the certification process "
        "(eligibility, exam format, scoring, scheduling) and for any "
        "topic that might be covered in the admin's knowledge base "
        "(e.g. GDPR, EU AI Act, trustworthy-AI principles)."
    )
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The exact question to search for. Pass the "
                    "user's wording verbatim unless they asked "
                    "multiple distinct things — then pass each "
                    "as a separate tool call."
                ),
            },
        },
        "required": ["query"],
    }
    requires_user = False
    has_llm_call  = True  # embedding call during retrieve_context

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                error="empty query",
            )
        try:
            chunks = retrieve_context(
                ctx.db, query,
                source_types=["faq", *SHARED_KNOWLEDGE_SOURCES])
        except Exception as e:
            # retrieve_context already swallows its own errors and
            # returns []; this is belt-and-braces against future
            # refactors.
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                error=f"retrieval failed: {e}",
            )

        if not chunks:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.EMPTY,
                content="",
                metadata={"chunks_returned": 0, "query": query},
            )

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.OK,
            content=build_context_block(chunks),
            citations=to_citations(chunks),
            metadata={
                "chunks_returned": len(chunks),
                "top_similarity": chunks[0].similarity if chunks else None,
                "query": query,
            },
        )


# Side-effect: register at import time.
register(FaqSearchTool())
