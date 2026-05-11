"""File parsers for admin-uploaded RAG sources.

Each parser takes raw bytes + a filename, returns a list of plain-text
chunks ready for embedding. Chunking strategy is per-file-type so the
semantic granularity matches the source's natural unit:

  - .txt / .md  → split on paragraphs (double newline), then re-bundle
                  into ~600-token chunks with ~50-token overlap
  - .xlsx       → one chunk per row (each row's cells joined as text)
  - .pdf        → one chunk per page (page numbers in metadata)
  - .docx       → split on paragraphs, re-bundle like .txt

No tokenizer dep — we approximate tokens as `len(text) // 4` (a
well-known rule-of-thumb for English text, ±10%). Good enough for
chunk sizing; the embedding API counts real tokens server-side.
"""
from dataclasses import dataclass
from io import BytesIO
from typing import Iterator


@dataclass
class ParsedChunk:
    content: str
    metadata: dict


# Approx chars per token (English). Used for chunk-size budgeting,
# NOT for billing.
_CHARS_PER_TOKEN = 4
# Target chunk size in TOKENS. ~600 tokens lets a k=4 retrieval pull
# ~2400 tokens of context — fits comfortably in a 4k system prompt
# budget without crowding out the user's question.
_TARGET_TOKENS = 600
_OVERLAP_TOKENS = 50

_TARGET_CHARS  = _TARGET_TOKENS  * _CHARS_PER_TOKEN
_OVERLAP_CHARS = _OVERLAP_TOKENS * _CHARS_PER_TOKEN


# ----------------------------------------------------------- public API
def parse_file(filename: str, content_type: str,
                data: bytes) -> list[ParsedChunk]:
    """Dispatch to the right parser. Returns at-least-one-chunk on
    success; raises ValueError on unsupported or unparseable input."""
    name_lower = filename.lower()
    if name_lower.endswith(".txt") or name_lower.endswith(".md"):
        return list(_parse_text(data, filename))
    if name_lower.endswith(".xlsx"):
        return list(_parse_xlsx(data, filename))
    if name_lower.endswith(".pdf"):
        return list(_parse_pdf(data, filename))
    if name_lower.endswith(".docx"):
        return list(_parse_docx(data, filename))
    raise ValueError(
        f"Unsupported file type: {filename}. "
        f"Supported: .txt, .md, .xlsx, .pdf, .docx")


# ----------------------------------------------------------- text/md
def _parse_text(data: bytes, filename: str) -> Iterator[ParsedChunk]:
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError(f"{filename} is empty.")
    yield from _windowed_paragraphs(text, filename)


# ----------------------------------------------------------- xlsx
def _parse_xlsx(data: bytes, filename: str) -> Iterator[ParsedChunk]:
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(data), data_only=True, read_only=True)
    yielded = 0
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        # Capture header row (if any) to give chunks context.
        header_row = None
        for row in ws.iter_rows(values_only=True):
            if header_row is None:
                header_row = [str(c) if c is not None else "" for c in row]
                continue
            cells = [str(c) for c in row if c is not None]
            if not cells:
                continue
            # Format as "col_a=val; col_b=val; ..." for cleaner retrieval.
            pairs: list[str] = []
            for i, val in enumerate(row):
                if val is None: continue
                key = (header_row[i] if i < len(header_row)
                                     else f"col{i+1}")
                pairs.append(f"{key}: {val}")
            if not pairs:
                continue
            yield ParsedChunk(
                content="; ".join(pairs),
                metadata={"sheet": sheet_name, "filename": filename},
            )
            yielded += 1
    if yielded == 0:
        raise ValueError(f"{filename} contained no data rows.")


# ----------------------------------------------------------- pdf
def _parse_pdf(data: bytes, filename: str) -> Iterator[ParsedChunk]:
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(data))
    if len(reader.pages) == 0:
        raise ValueError(f"{filename} has no pages.")
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        # Pages can be long — apply paragraph windowing per page so we
        # don't ship a 5K-token blob as one chunk.
        for sub in _windowed_paragraphs(text, filename,
                                         base_metadata={"page": i + 1}):
            yield sub


# ----------------------------------------------------------- docx
def _parse_docx(data: bytes, filename: str) -> Iterator[ParsedChunk]:
    from docx import Document
    doc = Document(BytesIO(data))
    text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if not text:
        raise ValueError(f"{filename} contains no paragraph text.")
    yield from _windowed_paragraphs(text, filename)


# ----------------------------------------------------------- windowing
def _windowed_paragraphs(text: str, filename: str, *,
                          base_metadata: dict | None = None
                          ) -> Iterator[ParsedChunk]:
    """Split text into paragraph-boundary-aware chunks of ≤ _TARGET_CHARS,
    with _OVERLAP_CHARS of context between consecutive chunks.

    Paragraph-aware so we don't slice through a thought; overlapping so
    a query that lands at the chunk boundary still sees both sides."""
    md = dict(base_metadata or {})
    md["filename"] = filename

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    current = ""
    chunk_idx = 0
    for p in paragraphs:
        if not current:
            current = p
            continue
        if len(current) + 2 + len(p) <= _TARGET_CHARS:
            current = current + "\n\n" + p
            continue
        # Flush current chunk.
        yield ParsedChunk(content=current, metadata={**md, "chunk_index": chunk_idx})
        chunk_idx += 1
        # Start next chunk with the tail of the previous for overlap +
        # this new paragraph.
        tail = current[-_OVERLAP_CHARS:] if _OVERLAP_CHARS < len(current) else current
        current = tail + "\n\n" + p
    if current:
        yield ParsedChunk(content=current, metadata={**md, "chunk_index": chunk_idx})
