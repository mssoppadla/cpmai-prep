"""Tests pinning the upload-corpus integration into topical handlers.

Operator scenario this guards (May 2026): admin uploaded a 254-chunk
CPMAI knowledge base via /admin/rag-sources expecting the assistant
to answer from it. Asking "What are GDPR Rules?" still got refused
because:

  1. The regex intent classifier didn't match GDPR → fell through to
     the FAQ default.
  2. FAQHandler retrieved only ``source_types=["faq"]`` — the 254
     upload chunks were never fetched, so the LLM never saw GDPR
     context.
  3. Same gap in ContentHandler (only ``["question_explanation"]``).

Fix: introduce ``SHARED_KNOWLEDGE_SOURCES`` (currently ``("upload",)``)
and spread it into both topical handlers' source_types filters. Also
fix the citation helpers to render upload chunks with their filename
so the UI doesn't show a bare "upload" tag.

These tests pin the wiring so the gap can't silently reappear.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.assistant.handlers.content_handler import ContentHandler
from app.services.assistant.handlers.faq_handler import FAQHandler
from app.services.assistant.rag.handler_support import (
    SHARED_KNOWLEDGE_SOURCES,
    _short_tag,
    _title,
    to_citations,
)
from app.services.assistant.rag.retrieve import RetrievedChunk


# ============================================================ shared constant

def test_shared_knowledge_sources_includes_upload():
    """Admin-uploaded docs MUST be in the shared pool — that's the whole
    point of the constant. If a future refactor accidentally drops it,
    the upload corpus goes orphaned again."""
    assert "upload" in SHARED_KNOWLEDGE_SOURCES


# ============================================================ FAQHandler

def test_faq_handler_retrieves_from_faq_and_upload():
    """REGRESSION GUARD: FAQHandler must spread SHARED_KNOWLEDGE_SOURCES
    into its source_types. Pre-fix it queried only ``['faq']`` and the
    254-chunk upload corpus was never fetched."""
    db = MagicMock()
    provider = MagicMock()
    provider.complete.return_value = "answer"

    request = MagicMock()
    request.message = "What are GDPR Rules?"
    request.history = []

    captured: dict = {}

    def fake_retrieve(_db, _query, *, source_types=None, k=None):
        captured["source_types"] = list(source_types) if source_types else []
        return []  # don't care about the chunks themselves here

    with patch(
        "app.services.assistant.handlers.faq_handler.retrieve_context",
        side_effect=fake_retrieve,
    ):
        FAQHandler(db, provider).respond(request, user=None)

    assert "faq" in captured["source_types"]
    assert "upload" in captured["source_types"], (
        "FAQHandler must include the upload corpus — without this, admin-"
        "uploaded knowledge bases are orphaned from retrieval")


# ============================================================ ContentHandler

def test_content_handler_retrieves_from_question_explanation_and_upload():
    """Same regression guard for ContentHandler. Pre-fix it queried
    only ``['question_explanation']`` so any upload-only topic
    (regulations, supporting study guides) was unreachable."""
    db = MagicMock()
    provider = MagicMock()
    provider.complete.return_value = "answer"

    request = MagicMock()
    request.message = "Explain CPMAI Phase 3"
    request.history = []

    captured: dict = {}

    def fake_retrieve(_db, _query, *, source_types=None, k=None):
        captured["source_types"] = list(source_types) if source_types else []
        return []

    with patch(
        "app.services.assistant.handlers.content_handler.retrieve_context",
        side_effect=fake_retrieve,
    ):
        ContentHandler(db, provider).respond(request, user=None)

    assert "question_explanation" in captured["source_types"]
    assert "upload" in captured["source_types"]


# ============================================================ citations

def _upload_chunk(content: str = "GDPR Article 5 covers...",
                   filename: str = "CPMAI_KB.md",
                   chunk_index: int = 12) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1, source_type="upload", source_id="rag/123",
        content=content,
        metadata={"filename": filename, "chunk_index": chunk_index},
        similarity=0.85,
    )


def test_upload_short_tag_includes_filename():
    """Citation chip must show the filename, not the bare 'upload'
    source_type. UI relies on this for clickable provenance."""
    c = _upload_chunk()
    assert _short_tag(c) == "Doc: CPMAI_KB.md"


def test_upload_short_tag_falls_back_when_filename_missing():
    """Defensive: if metadata is somehow stripped (older rows from
    before the chunker stored filename), don't crash — render a
    generic 'Document' label."""
    c = RetrievedChunk(
        chunk_id=1, source_type="upload", source_id="rag/x",
        content="...", metadata={}, similarity=0.7,
    )
    assert _short_tag(c) == "Document"


def test_upload_title_includes_chunk_index():
    """Multiple chunks from the same doc must be distinguishable in
    the citations tray, otherwise they all look like duplicates."""
    c = _upload_chunk(filename="CPMAI_KB.md", chunk_index=42)
    assert _title(c) == "CPMAI_KB.md (#42)"


def test_to_citations_round_trips_upload_chunk():
    """End-to-end: an upload chunk goes through to_citations and comes
    out with a meaningful source + title that the frontend can render
    without showing 'upload' anywhere user-facing."""
    cites = to_citations([_upload_chunk()])
    assert len(cites) == 1
    cite = cites[0]
    assert cite["source"] == "Doc: CPMAI_KB.md"
    assert "CPMAI_KB.md" in cite["title"]
    # No deep-link for uploads (raw bytes are discarded after chunking).
    assert cite["url"] is None
