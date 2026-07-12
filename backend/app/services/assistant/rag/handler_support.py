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


# Source types that represent admin-curated knowledge applicable to ANY
# subject-matter handler (FAQ, Content):
#   - "upload"       — admin-uploaded reference docs (/admin/rag-sources)
#   - "content_page" — published, publicly-visible CMS pages
#   - "course"       — the published course catalog (titles, outcomes,
#                      prices) so "what courses do you offer" works from
#                      any topical route
#   - "zoom_session" — upcoming/live class sessions WITH their dates so
#                      "when is the next live class" is answerable
# Excludes:
#   - "plan" (pricing data; lives in AccountHandler/pricing_lookup)
#   - "question_explanation" (ContentHandler's primary source)
#   - "faq" (FAQHandler's primary source)
#
# Handlers spread this into their source_types filter so this shared
# site-knowledge pool is searchable from any topical handler — in BOTH
# the legacy flow and the agentic *_search tools. Similarity ranking
# keeps irrelevant sources out of the top-k.
SHARED_KNOWLEDGE_SOURCES: tuple[str, ...] = (
    "upload", "content_page", "course", "zoom_session",
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
    if c.source_type == "course":
        title = c.metadata.get("course_title") or "Course"
        return f"Course: {title}"
    if c.source_type == "content_page":
        title = c.metadata.get("page_title") or "Page"
        return f"Page: {title}"
    if c.source_type == "zoom_session":
        return "Live class"
    if c.source_type == "upload":
        # Admin-uploaded reference document. The chunker stores the
        # filename in metadata; surface it here so a citation chip
        # shows e.g. "Doc: CPMAI_Knowledge_Base.md" rather than just
        # the opaque "upload" source_type.
        fname = c.metadata.get("filename")
        return f"Doc: {fname}" if fname else "Document"
    return c.source_type


def _title(c: RetrievedChunk) -> str:
    if c.source_type == "faq":
        return c.metadata.get("faq_question") or c.content[:120]
    if c.source_type == "plan":
        return c.metadata.get("plan_name") or "Pricing plan"
    if c.source_type == "course":
        return c.metadata.get("course_title") or c.content[:120]
    if c.source_type == "content_page":
        return c.metadata.get("page_title") or c.content[:120]
    if c.source_type == "zoom_session":
        return c.metadata.get("session_title") or c.content[:120]
    if c.source_type == "upload":
        # Prefix with filename + chunk index when available so multiple
        # chunks from the same doc are distinguishable in the citations
        # tray. Falls back to a content excerpt otherwise.
        fname = c.metadata.get("filename")
        idx   = c.metadata.get("chunk_index")
        if fname and idx is not None:
            return f"{fname} (#{idx})"
        if fname:
            return fname
    return c.content[:120]


def _deep_link(c: RetrievedChunk) -> str | None:
    if c.source_type == "plan":
        slug = c.metadata.get("plan_slug")
        return f"/pricing#{slug}" if slug else "/pricing"
    if c.source_type == "faq":
        # No deep-link per FAQ row today; landing FAQ section anchor.
        return "/#faq-heading"
    if c.source_type == "course":
        slug = c.metadata.get("course_slug")
        return f"/courses/{slug}" if slug else "/courses"
    if c.source_type == "content_page":
        slug = c.metadata.get("page_slug")
        return f"/pages/{slug}" if slug else None
    if c.source_type == "zoom_session":
        # Sessions are joined from the signed-in dashboard; anonymous
        # visitors land on the courses page which advertises them.
        return "/dashboard"
    # Uploaded docs are admin-only — no public deep-link to the raw
    # file (we discard the bytes after chunking; only the rag_chunks
    # rows persist). Citation chip stays clickable but routes nowhere.
    return None
