"""Regression tests for the RAG file-parser chunker.

The headline failure this file pins down: shipping a single chunk
larger than OpenAI's 8192-token-per-input embedding limit. When that
happens, the embedding API rejects the WHOLE batch with
``Invalid 'input[N]': maximum input length is 8192 tokens`` and the
admin sees an empty rag_chunks table after a "successful" upload.

The fix lives in ``_split_oversized`` (file_parsers.py). These tests
guard each parser path that can produce an oversized chunk:

  * .txt / .md  with a single paragraph larger than the target
  * .pdf       with a single page that has no paragraph breaks
                (we simulate by using _windowed_paragraphs directly)
  * .xlsx       with a single row containing a giant text cell

If you change ``_TARGET_CHARS`` or ``_MAX_CHARS``, these tests still
hold — they assert against the constants, not against magic numbers.
"""
from io import BytesIO

import pytest

from app.services.assistant.rag.file_parsers import (
    _MAX_CHARS,
    _TARGET_CHARS,
    _split_oversized,
    _windowed_paragraphs,
    parse_file,
)


# ============================================================ _split_oversized

def test_split_oversized_passes_through_short_text():
    """Common case: input fits the budget, yielded once unchanged."""
    text = "Short paragraph that fits under the target."
    chunks = list(_split_oversized(text))
    assert chunks == [text]


def test_split_oversized_splits_long_text_on_sentences():
    """Many short sentences over the budget → bundled into multiple
    chunks at sentence boundaries, each under the soft cap."""
    sentence = "This is a sentence about CPMAI Phase 3 methodology. "
    # ~52 chars × 1000 = ~52k chars, well over _TARGET_CHARS (2400).
    text = sentence * 1000
    chunks = list(_split_oversized(text))
    assert len(chunks) > 1
    for c in chunks:
        # Each chunk must be at or under the soft cap (with a small
        # tolerance for the trailing sentence).
        assert len(c) <= _TARGET_CHARS + len(sentence)


def test_split_oversized_hard_cuts_one_giant_sentence():
    """Pathological case: a single 'sentence' with no period punctuation
    larger than the hard cap. Must hard-cut to satisfy the embed API
    rather than yielding it whole."""
    # 50k chars, no sentence boundaries.
    giant = "a" * 50_000
    chunks = list(_split_oversized(giant))
    # Multiple sub-chunks, each within the HARD cap (this is the
    # invariant the embedding API actually enforces).
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= _MAX_CHARS, (
            f"chunk len {len(c)} exceeds hard cap {_MAX_CHARS} — "
            "would 400 the embedding API")


# ========================================================== txt/md path

def test_parse_text_with_single_huge_paragraph_splits_it():
    """The original prod failure: an admin uploaded a doc whose
    paragraph (PDF page extracted as one block, FAQ with no blank
    lines, etc.) was larger than the embed API's 8192-token limit.
    Without the splitter, the chunker yielded it whole and the embed
    batch 400'd. This test pins the fix: NO chunk yielded by parse_file
    may exceed the hard cap."""
    # 80k chars in a SINGLE paragraph (no double-newlines).
    long_para = "CPMAI Phase 3 covers data engineering. " * 2200
    raw = long_para.encode("utf-8")
    chunks = parse_file("study-guide.txt", "text/plain", raw)

    assert len(chunks) > 1, "expected multiple chunks; got one giant chunk"
    for c in chunks:
        assert len(c.content) <= _MAX_CHARS, (
            f"chunk len {len(c.content)} > {_MAX_CHARS} — "
            "embed API would reject this batch")


def test_parse_text_normal_paragraphs_unchanged():
    """Sanity: a normal multi-paragraph doc still chunks reasonably,
    no spurious splits introduced by the new safety net."""
    text = "\n\n".join([
        "This is paragraph one. It is normal-sized.",
        "This is paragraph two. Also normal.",
        "And a third one for good measure.",
    ])
    chunks = parse_file("normal.txt", "text/plain", text.encode("utf-8"))
    assert len(chunks) >= 1
    # Total content preserved (modulo paragraph joining whitespace).
    joined = "\n\n".join(c.content for c in chunks)
    assert "paragraph one" in joined
    assert "paragraph two" in joined
    assert "third one" in joined


# ========================================================== _windowed_paragraphs

def test_windowed_paragraphs_handles_oversized_paragraph():
    """Direct test on the windower: a SINGLE oversized paragraph mixed
    in with normal ones must split, not propagate as one chunk."""
    normal_para = "Short intro paragraph."
    long_para = "Very long technical content. " * 2000  # ~58k chars
    closing = "Short closing paragraph."
    text = "\n\n".join([normal_para, long_para, closing])

    chunks = list(_windowed_paragraphs(text, "test.txt"))

    # At least: 1 chunk for normal_para region + N chunks for long_para
    # split + 1 for closing. Definitely more than 1.
    assert len(chunks) >= 3
    # Hard cap holds for every chunk.
    for c in chunks:
        assert len(c.content) <= _MAX_CHARS

    # Metadata still flows through (filename + chunk_index).
    assert chunks[0].metadata["filename"] == "test.txt"
    assert all("chunk_index" in c.metadata for c in chunks)


# ========================================================== xlsx path

def test_parse_xlsx_oversized_cell_splits_safely():
    """A row with a single giant text cell (e.g. free-form description
    column with a copy-pasted document) must split, not blow up the
    embed batch. Other rows in the same sheet stay as their own
    chunks."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["title", "body"])
    ws.append(["short row", "small text"])
    # Giant cell — 60k chars in one cell.
    ws.append(["long row", "Repeated content. " * 4000])
    ws.append(["another short", "also small"])

    buf = BytesIO()
    wb.save(buf)
    raw = buf.getvalue()

    chunks = parse_file("data.xlsx",
                         "application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet", raw)

    # 2 normal rows + at least 2 sub-chunks from the giant row = 4+.
    assert len(chunks) >= 4
    for c in chunks:
        assert len(c.content) <= _MAX_CHARS

    # The two short rows are still findable by their unique content.
    joined = " | ".join(c.content for c in chunks)
    assert "short row" in joined
    assert "another short" in joined


def test_parse_text_empty_file_raises():
    """Pre-existing contract: empty input is a user error, not silent
    no-op. Re-pinning here so the hotfix doesn't accidentally silence
    it (the splitter early-returns on short text — easy to break)."""
    with pytest.raises(ValueError):
        parse_file("empty.txt", "text/plain", b"   \n\n   ")
