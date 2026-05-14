"""pricing_lookup tool — fetch plan / pricing information.

Equivalent to the retrieval half of the legacy AccountHandler. Uses
the same ``plan``-source RAG path so price changes show up
immediately after an admin saves a plan (the plan-reindex hook
re-embeds on each save).

Sources searched:
  * ``plan`` — per-plan chunks (name, price, duration, features)

Always emits a ``View pricing`` suggested action when chunks were
found, so synthesis can pass through a "see all plans" deep-link in
the response — same UX affordance the legacy handler shipped.

Cost per call: one embedding call.
"""
from __future__ import annotations

from typing import Any

from app.services.assistant.agentic.registry import register
from app.services.assistant.agentic.types import (
    Tool, ToolContext, ToolResult, ToolStatus,
)
from app.services.assistant.rag.handler_support import (
    build_context_block, retrieve_context, to_citations,
)


class PricingLookupTool(Tool):
    name = "pricing_lookup"
    description = (
        "Look up CPMAI Prep subscription plans, pricing, billing "
        "details, offers, and refund policy. Use this for any "
        "question about cost, plan features, payment, or billing. "
        "Returns relevant plan rows + a 'View pricing' deep-link "
        "action."
    )
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Plain-text description of what the user is "
                    "asking about — e.g. 'monthly plan price', "
                    "'refund policy', 'exam bundle cost'."
                ),
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
                ctx.db, query, source_types=["plan"])
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
                # Even when no specific plan matched, give synthesis
                # the pricing-page link as a fallback affordance.
                suggested_actions=[{"label": "View pricing", "url": "/pricing"}],
                metadata={"chunks_returned": 0, "query": query},
            )

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.OK,
            content=build_context_block(chunks),
            citations=to_citations(chunks),
            suggested_actions=[{"label": "View pricing", "url": "/pricing"}],
            metadata={
                "chunks_returned": len(chunks),
                "top_similarity": chunks[0].similarity if chunks else None,
                "query": query,
            },
        )


register(PricingLookupTool())
