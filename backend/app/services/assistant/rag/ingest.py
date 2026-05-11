"""RAG ingestion — embed source content and upsert into rag_chunks.

Three entry points, in increasing scope:

  index_chunk(db, record)      — write/replace one chunk
  reindex_source_id(db, ...)   — re-embed one source row (FAQ #5,
                                 plan #2, etc.). Called by the
                                 on-save CRUD hooks.
  reindex_all(db, source_types=None) — full corpus rebuild. Called
                                       by the admin "reindex" button.

Upsert semantics: deleting-then-inserting per (source_type, source_id,
chunk_index) keeps the row count exact even when a row used to have
N chunks and now has fewer (Day 2's long uploads matter here).

Embedding cost discipline: we batch every embed_batch call. A full
reindex of the current corpus is a single API roundtrip per source
type — pennies, not dollars.
"""
import structlog
from sqlalchemy.orm import Session

from app.models.rag_chunk import RagChunk
from app.services.assistant.embeddings.registry import EmbeddingRegistry
from app.services.assistant.rag.sources import (
    ChunkRecord, SOURCES, SourceAdapter,
)

log = structlog.get_logger("assistant.rag.ingest")


def index_chunks(db: Session, records: list[ChunkRecord]) -> int:
    """Embed + upsert a list of chunks. Returns count written.

    All chunks must come from a single (source_type, source_id) pair —
    the upsert path deletes any existing chunks for that pair first to
    handle "row used to have 5 chunks, now has 3" cleanly.
    """
    if not records:
        return 0
    first = records[0]
    for r in records[1:]:
        assert r.source_type == first.source_type, "mixed source_types"
        assert r.source_id == first.source_id, "mixed source_ids"

    provider = EmbeddingRegistry.get_active()
    vectors = provider.embed_batch([r.content for r in records])

    # Replace-not-merge: delete existing chunks for this source row,
    # then insert the fresh ones. Idempotent + simple.
    (db.query(RagChunk)
     .filter(RagChunk.source_type == first.source_type,
             RagChunk.source_id == first.source_id,
             RagChunk.tenant_id.is_(None))                # single-tenant today
     .delete(synchronize_session=False))

    for r, vec in zip(records, vectors):
        db.add(RagChunk(
            source_type=r.source_type,
            source_id=r.source_id,
            chunk_index=r.chunk_index,
            content=r.content,
            provider=provider.name,
            model=provider.model,
            embedding=vec,
            chunk_metadata=r.metadata or {},
        ))
    db.commit()
    log.info("rag.indexed",
             source_type=first.source_type,
             source_id=first.source_id,
             chunks=len(records),
             provider=provider.name, model=provider.model)
    return len(records)


def reindex_source_id(db: Session, source_type: str, source_id: str) -> int:
    """Re-embed one specific source row. Called by CRUD hooks when a
    FAQ entry / plan / question is created/updated."""
    adapter = SOURCES.get(source_type)
    if not adapter:
        return 0
    records = list(adapter.iter_chunks_for_id(db, source_id))
    if not records:
        # Source row was deleted or made inactive — clean up stale chunks.
        (db.query(RagChunk)
         .filter(RagChunk.source_type == source_type,
                 RagChunk.source_id == source_id,
                 RagChunk.tenant_id.is_(None))
         .delete(synchronize_session=False))
        db.commit()
        return 0
    return index_chunks(db, records)


def reindex_all(db: Session, source_types: list[str] | None = None
                ) -> dict[str, int]:
    """Full reindex. Returns count per source_type. Safe to re-run."""
    types = source_types or list(SOURCES.keys())
    results: dict[str, int] = {}
    for st in types:
        adapter = SOURCES.get(st)
        if not adapter:
            results[st] = 0
            continue
        count = 0
        # Group records by source_id so each (source_type, source_id)
        # batch is upserted atomically.
        by_id: dict[str, list[ChunkRecord]] = {}
        for rec in adapter.iter_chunks(db):
            by_id.setdefault(rec.source_id, []).append(rec)
        for source_id, recs in by_id.items():
            count += index_chunks(db, recs)
        results[st] = count
        log.info("rag.source_reindexed", source_type=st, chunks=count)
    return results


def reindex_quietly(db: Session, source_type: str, source_id: int | str) -> None:
    """Fire-and-forget wrapper for CRUD hook call sites — never raises.

    The CRUD endpoint's primary job is committing the user's change.
    A re-embed failure (OpenAI rate limit, network blip) is recoverable
    later via the admin "reindex" button; it must not crash the
    user-visible save. Logs the failure for operator visibility.
    """
    try:
        reindex_source_id(db, source_type, str(source_id))
    except Exception as e:
        log.warning("rag.reindex_failed_silently",
                    source_type=source_type, source_id=source_id,
                    error=str(e))
