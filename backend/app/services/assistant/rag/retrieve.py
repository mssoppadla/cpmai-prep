"""RAG retrieval — find the top-k chunks most relevant to a query.

Pluggable behind a `Retriever` interface so future vector stores
(Pinecone, Weaviate, OpenSearch) drop in without touching handlers.
Today's only implementation is `PgVectorRetriever` against our
postgres+pgvector instance.

Cosine similarity ranking: `1 - (embedding <=> query_embedding)` in
pgvector. Higher = more similar. The `min_similarity` threshold from
`rag.min_similarity` setting filters out borderline noise (e.g., a
user's "hi" wouldn't match anything substantive — we'd rather return
zero chunks than four irrelevant ones).
"""
from dataclasses import dataclass
from typing import Iterable
import structlog

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.core.settings_store import settings_store
from app.models.rag_chunk import RagChunk
from app.services.assistant.embeddings.registry import EmbeddingRegistry

log = structlog.get_logger("assistant.rag.retrieve")


@dataclass
class RetrievedChunk:
    """One match. `similarity` is in 0..1 (higher = better). Handlers
    use this to build a "Sources" section in the response."""
    chunk_id: int
    source_type: str
    source_id: str
    content: str
    similarity: float
    metadata: dict


class Retriever:
    """Backend-agnostic retrieval interface. Implementations must:
      - embed the query themselves (so the caller doesn't need to)
      - return ≤ k chunks, sorted by descending similarity
      - filter out chunks below `min_similarity` (caller-pinned)
    """
    def retrieve(self, db: Session, query: str, *,
                 k: int | None = None,
                 source_types: Iterable[str] | None = None,
                 min_similarity: float | None = None,
                 ) -> list[RetrievedChunk]:
        raise NotImplementedError


class PgVectorRetriever(Retriever):
    """pgvector-backed retrieval using cosine distance + HNSW index."""

    def retrieve(self, db: Session, query: str, *,
                 k: int | None = None,
                 source_types: Iterable[str] | None = None,
                 min_similarity: float | None = None,
                 ) -> list[RetrievedChunk]:
        if not query or not query.strip():
            return []

        k = k if k is not None else settings_store.get_int("rag.top_k", 4)
        min_sim = (min_similarity if min_similarity is not None
                   else settings_store.get_float("rag.min_similarity", 0.3))

        provider = EmbeddingRegistry.get_active()
        query_vec = provider.embed_one(query)

        # Build params + WHERE clause for optional source_types filter.
        params: dict = {"q_emb": _vec_literal(query_vec), "k": k}
        where_clauses = ["tenant_id IS NULL",
                          # Only chunks embedded with the SAME provider+model
                          # — vectors from different models live in
                          # different spaces and aren't comparable.
                          "provider = :provider",
                          "model = :model"]
        params["provider"] = provider.name
        params["model"] = provider.model

        if source_types:
            sts = list(source_types)
            placeholders = ", ".join(f":st{i}" for i in range(len(sts)))
            where_clauses.append(f"source_type IN ({placeholders})")
            for i, st in enumerate(sts):
                params[f"st{i}"] = st

        where_sql = " AND ".join(where_clauses)
        sql = sa_text(f"""
            SELECT id, source_type, source_id, content,
                   1 - (embedding <=> CAST(:q_emb AS vector)) AS similarity,
                   metadata
            FROM rag_chunks
            WHERE {where_sql}
            ORDER BY embedding <=> CAST(:q_emb AS vector)
            LIMIT :k
        """)
        rows = db.execute(sql, params).all()

        out: list[RetrievedChunk] = []
        for r in rows:
            if r.similarity < min_sim:
                continue
            out.append(RetrievedChunk(
                chunk_id=r.id,
                source_type=r.source_type,
                source_id=r.source_id,
                content=r.content,
                similarity=float(r.similarity),
                metadata=r.metadata or {},
            ))
        log.info("rag.retrieved",
                 query_chars=len(query), k_requested=k,
                 returned=len(out),
                 top_similarity=(out[0].similarity if out else None))
        return out


# Default instance used by handlers. Swap by reassigning `default_retriever`
# at app startup if a different backend is configured.
default_retriever: Retriever = PgVectorRetriever()


def _vec_literal(vec: list[float]) -> str:
    """pgvector accepts a string literal like '[0.1, 0.2, ...]' when
    cast to `vector`. Faster than driver-side adaptation."""
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"
