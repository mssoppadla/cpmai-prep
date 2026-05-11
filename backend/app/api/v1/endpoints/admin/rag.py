"""Admin RAG controls — reindex on demand, view corpus stats.

Day 2 will add file-upload endpoints to this same router.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import AppError
from app.models.rag_chunk import RagChunk
from app.models.user import User
from app.services.assistant.rag.ingest import reindex_all
from app.services.assistant.rag.sources import SOURCES

router = APIRouter()


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
