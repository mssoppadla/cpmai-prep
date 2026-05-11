"""Shared RAG support for assistant handlers.

Every retrieving handler does the same three things:
  1. Retrieve top-k chunks scoped to its source_type(s).
  2. Build a context block to prepend to the LLM system prompt.
  3. Build a citations list to attach to the response.

Centralising it keeps handlers small + ensures consistent citation
formatting + makes the retrieval policy (k, similarity threshold,
provider/model filtering) tunable from one place.

Why not put this on `Retriever` itself: retrieval is store-agnostic;
prompt assembly is handler-policy. Keeping them separate means future
backends (Pinecone, etc.) only implement `Retriever.retrieve` and the
prompt-building logic continues to work.
"""
from typing import Iterable
from sqlalchemy.orm import Session

from app.services.assistant.rag.retrieve import (
    RetrievedChunk, default_retriever,
)


def retrieve_context(
    db: Session, query: str, *, source_types: Iterable[str] | None = None,
    k: int | None = None,
) -> list[RetrievedChunk]:
    """Retrieve top-k chunks for the query, scoped to given source_types.

    Returns an empty list if RAG is not configured (no embeddings
    provider, no chunks indexed, retrieval throws). Handlers should
    tolerate empty results and answer from the LLM's prior knowledge —
    the chat stays usable even mid-rollout when the corpus is empty.
    """
    try:
        return default_retriever.retrieve(
            db, query, source_types=source_types, k=k)
    except Exception:
        # Embeddings not configured / pgvector not available / API
        # transient — fall through to a no-RAG answer rather than
        # 500'ing the chat. Operator sees the error in structured logs.
        return []


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks for inclusion in the LLM's system prompt.

    Numbered for downstream citation reference. Trimmed to keep token
    cost predictable — each chunk capped at ~800 chars (≈ 200 tokens),
    so a k=4 retrieval contributes ~800 tokens of context.
    """
    if not chunks:
        return ""
    parts = ["Relevant information from our knowledge base:\n"]
    for i, c in enumerate(chunks, start=1):
        excerpt = c.content[:800]
        if len(c.content) > 800:
            excerpt += "…"
        parts.append(f"[Source {i}] ({c.source_type}/{c.source_id})\n{excerpt}\n")
    parts.append(
        "\nWhen answering, cite the source numbers in square brackets "
        "where relevant. If none of the sources apply, say so honestly."
    )
    return "\n".join(parts)


def to_citations(chunks: list[RetrievedChunk]) -> list[dict]:
    """Convert chunks to the wire `citations` shape on AssistantResponse.

    Schema (matches existing `AssistantCitation` typing):
      source — short tag the UI renders (e.g. "FAQ", "Plan: Exam Bundle")
      title  — full source text (or excerpt)
      url    — deep link the UI can route to (optional)
    """
    out: list[dict] = []
    for c in chunks:
        out.append({
            "source": _short_tag(c),
            "title":  _title(c),
            "url":    _deep_link(c),
        })
    return out


def _short_tag(c: RetrievedChunk) -> str:
    if c.source_type == "faq":
        return "FAQ"
    if c.source_type == "plan":
        name = c.metadata.get("plan_name") or "Plan"
        return f"Plan: {name}"
    if c.source_type == "question_explanation":
        return "Question explanation"
    return c.source_type


def _title(c: RetrievedChunk) -> str:
    if c.source_type == "faq":
        return c.metadata.get("faq_question") or c.content[:120]
    if c.source_type == "plan":
        return c.metadata.get("plan_name") or "Pricing plan"
    return c.content[:120]


def _deep_link(c: RetrievedChunk) -> str | None:
    if c.source_type == "plan":
        slug = c.metadata.get("plan_slug")
        return f"/pricing#{slug}" if slug else "/pricing"
    if c.source_type == "faq":
        # No deep-link per FAQ row today; landing FAQ section anchor.
        return "/#faq-heading"
    return None
