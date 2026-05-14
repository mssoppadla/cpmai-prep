"""content_search tool — RAG retrieval over the question-explanation +
upload corpora.

Equivalent in retrieval policy to the legacy ContentHandler. Use for
"what is X / explain Y / define Z" style questions about CPMAI
concepts, the 6-phase methodology, or topics covered by admin-
uploaded materials.

Sources searched:
  * ``question_explanation`` — per-question "why this is the answer"
    notes admins author; richest source of CPMAI-specific explanatory
    text
  * ``upload`` (and any future SHARED_KNOWLEDGE_SOURCES)

Cost per call: one embedding call.
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


class ContentSearchTool(Tool):
    name = "content_search"
    description = (
        "Search CPMAI conceptual content (the 6-phase methodology, "
        "per-question 'why this is the right answer' explanations) "
        "and any admin-uploaded reference materials. Use this for "
        "'what is X', 'explain Y', 'define Z' style questions about "
        "CPMAI concepts, AI/ML concepts, or topics that might be "
        "covered in the uploaded knowledge base."
    )
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The concept or topic the user is asking about.",
            },
        },
        "required": ["query"],
    }
    requires_user = False
    has_llm_call  = True

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
                source_types=["question_explanation",
                               *SHARED_KNOWLEDGE_SOURCES])
        except Exception as e:
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


register(ContentSearchTool())
