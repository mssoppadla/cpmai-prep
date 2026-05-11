"""Admin RAG controls — reindex on demand, view corpus stats, upload sources.

File uploads (.txt/.md/.pdf/.docx/.xlsx) get parsed, chunked, embedded,
and stored as rag_chunks with source_type='upload'. Raw bytes are NOT
kept — once chunked, the rag_chunks rows are the source of truth.
"""
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import AppError, NotFoundError
from app.models.rag_chunk import RagChunk
from app.models.rag_document import RagDocument
from app.models.user import User
from app.services.assistant.rag.file_parsers import parse_file
from app.services.assistant.rag.ingest import index_chunks, reindex_all
from app.services.assistant.rag.sources import SOURCES, ChunkRecord

router = APIRouter()

# Hard cap so a runaway upload can't blow our OpenAI budget or memory.
# 20 MB is generous for documents; PDFs over this size are almost always
# scanned image PDFs we couldn't extract text from anyway.
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.get("/status")
def rag_status(db: Session = Depends(get_db),
               admin: User = Depends(get_admin_user)):
    """Per-source row count + last-indexed timestamp.

    Admin uses this to confirm a reindex took, see whether a source is
    actually populated, and audit drift between the source row count
    and the chunk count.
    """
    rows = (db.query(
        RagChunk.source_type,
        func.count(RagChunk.id).label("chunks"),
        func.max(RagChunk.updated_at).label("last_indexed"),
        func.max(RagChunk.provider).label("provider"),
        func.max(RagChunk.model).label("model"),
    ).group_by(RagChunk.source_type).all())
    by_source = {
        r.source_type: {
            "chunks": r.chunks,
            "last_indexed": r.last_indexed,
            "provider": r.provider,
            "model": r.model,
        }
        for r in rows
    }
    # Fill in zero-row entries so the UI always shows every known source.
    for st in SOURCES.keys():
        by_source.setdefault(st, {
            "chunks": 0, "last_indexed": None,
            "provider": None, "model": None,
        })
    return {"sources": by_source}


@router.post("/reindex")
def reindex(db: Session = Depends(get_db),
            admin: User = Depends(get_admin_user)):
    """Full reindex of all source types.

    Synchronous — fine for the current corpus size (<200 rows total).
    If the corpus grows past a few hundred chunks, move this to a
    background task; the function itself is already idempotent.
    """
    try:
        result = reindex_all(db)
    except RuntimeError as e:
        # EmbeddingRegistry raises if no provider is configured.
        raise AppError(str(e), status_code=400)
    audit_log(db, admin.id, "rag.reindex_all", {"counts": result})
    return {"counts": result}


# ----------------------------------------------------------- uploads
@router.post("/upload")
async def upload_document(file: UploadFile = File(...),
                          db: Session = Depends(get_db),
                          admin: User = Depends(get_admin_user)):
    """Parse → chunk → embed → store. Returns RagDocument summary.

    Whole pipeline runs inline so the admin sees immediate success/fail
    feedback. If embedding fails (rate limit, network), the RagDocument
    row is rolled back so we don't show "indexed" with zero chunks.
    """
    data = await file.read()
    if not data:
        raise AppError("Empty file.", status_code=400)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise AppError(
            f"File too large ({len(data)} bytes). "
            f"Max {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            status_code=413)

    try:
        parsed = parse_file(file.filename, file.content_type or "", data)
    except ValueError as e:
        raise AppError(str(e), status_code=400)
    if not parsed:
        raise AppError(f"No extractable text in {file.filename}.",
                       status_code=400)

    # Create the RagDocument row first so we have an id to use as source_id.
    doc = RagDocument(
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        chunk_count=0,
        status="ingested",
        created_by=admin.id,
    )
    db.add(doc)
    db.flush()                                  # populate doc.id

    records = [
        ChunkRecord(
            source_type="upload",
            source_id=str(doc.id),
            chunk_index=i,
            content=p.content,
            metadata={**p.metadata, "document_id": doc.id},
        )
        for i, p in enumerate(parsed)
    ]
    try:
        count = index_chunks(db, records)
    except RuntimeError as e:
        # No embedding provider configured — roll back the document row.
        db.rollback()
        raise AppError(str(e), status_code=400)
    except Exception as e:
        db.rollback()
        raise AppError(f"Embedding failed: {e}", status_code=502)

    # index_chunks commits internally; refresh + persist final count.
    doc.chunk_count = count
    db.commit()
    audit_log(db, admin.id, "rag.upload",
              {"document_id": doc.id, "filename": file.filename,
               "chunks": count})
    return _doc_out(doc)


@router.get("/uploads")
def list_uploads(db: Session = Depends(get_db),
                 admin: User = Depends(get_admin_user)):
    """Most-recent first. Admin uses this to audit what's in the corpus
    and to remove stale uploads."""
    rows = (db.query(RagDocument)
            .order_by(RagDocument.created_at.desc())
            .all())
    return {"documents": [_doc_out(r) for r in rows]}


@router.delete("/uploads/{doc_id}")
def delete_upload(doc_id: int,
                  db: Session = Depends(get_db),
                  admin: User = Depends(get_admin_user)):
    """Remove the document + its chunks. Hard-delete: there's no undo,
    but a re-upload is the same file."""
    doc = db.get(RagDocument, doc_id)
    if not doc:
        raise NotFoundError("Document not found.")
    (db.query(RagChunk)
     .filter(RagChunk.source_type == "upload",
             RagChunk.source_id == str(doc.id))
     .delete(synchronize_session=False))
    db.delete(doc)
    db.commit()
    audit_log(db, admin.id, "rag.upload_deleted",
              {"document_id": doc_id, "filename": doc.filename})
    return {"deleted": True}


def _doc_out(doc: RagDocument) -> dict:
    return {
        "id": doc.id,
        "filename": doc.filename,
        "content_type": doc.content_type,
        "size_bytes": doc.size_bytes,
        "chunk_count": doc.chunk_count,
        "status": doc.status,
        "created_by": doc.created_by,
        "created_at": doc.created_at,
    }
