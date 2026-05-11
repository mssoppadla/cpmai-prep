"""Source adapters — turn each kind of CPMAI content into ingestable chunks.

Adding a new source = new adapter class + register it in SOURCES.
Schema/migrations don't change; rag_chunks stores `source_type` as a
free-form tag.

Each adapter exposes:
  source_type      — the string tag stored on rag_chunks
  iter_chunks(db)  — generator yielding ChunkRecord per piece of content

ChunkRecord is what `ingest.py` upserts into rag_chunks.

Today's adapters:
  - FAQAdapter             — one chunk per FAQ row
  - PlanAdapter            — one chunk per pricing plan (name + description)
  - QuestionExplanationAdapter — one chunk per question's explanation

Day 2 will add:
  - UploadAdapter — parses xlsx/pdf/docx files admin uploaded

Single-source-of-truth design: when the underlying row changes, we
re-run the adapter for ONE source_id (cheap), not the whole corpus.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator

from sqlalchemy.orm import Session

from app.models.faq import FaqItem
from app.models.plan import Plan
from app.models.question import Question


@dataclass
class ChunkRecord:
    """One piece of text to embed + upsert.

    `source_type` + `source_id` uniquely identify what this chunk
    represents in the original domain — for single-chunk-per-row
    adapters, chunk_index=0.
    """
    source_type: str
    source_id: str
    chunk_index: int = 0
    content: str = ""
    # `metadata` surfaces in citations to the end-user (e.g. FAQ
    # question text, Plan name) so the chat can show a useful pointer
    # without round-tripping back to the source table.
    metadata: dict = field(default_factory=dict)


class SourceAdapter(ABC):
    """One adapter per content source. Stateless."""
    source_type: str = ""

    @abstractmethod
    def iter_chunks(self, db: Session) -> Iterator[ChunkRecord]:
        """Yield every chunk for this source. Called by full-reindex."""

    @abstractmethod
    def iter_chunks_for_id(self, db: Session, source_id: str
                            ) -> Iterator[ChunkRecord]:
        """Yield chunks for ONE specific source row — called by the
        on-save reindex hook so we don't re-embed everything when one
        FAQ entry is edited."""


class FAQAdapter(SourceAdapter):
    source_type = "faq"

    def iter_chunks(self, db: Session) -> Iterator[ChunkRecord]:
        for row in db.query(FaqItem).filter_by(is_active=True).all():
            yield from self._chunks(row)

    def iter_chunks_for_id(self, db: Session, source_id: str
                            ) -> Iterator[ChunkRecord]:
        row = db.query(FaqItem).filter_by(id=int(source_id)).first()
        if row and row.is_active:
            yield from self._chunks(row)

    @staticmethod
    def _chunks(row: FaqItem) -> Iterator[ChunkRecord]:
        # Q + A together as one chunk. Format the text so the embedding
        # captures both the question intent and the answer content — a
        # bare answer alone misses queries that paraphrase the question.
        text = f"Question: {row.question}\n\nAnswer: {row.answer}"
        yield ChunkRecord(
            source_type="faq", source_id=str(row.id), chunk_index=0,
            content=text,
            metadata={"faq_question": row.question},
        )


class PlanAdapter(SourceAdapter):
    source_type = "plan"

    def iter_chunks(self, db: Session) -> Iterator[ChunkRecord]:
        for row in db.query(Plan).filter_by(is_active=True).all():
            yield from self._chunks(row)

    def iter_chunks_for_id(self, db: Session, source_id: str
                            ) -> Iterator[ChunkRecord]:
        row = db.query(Plan).filter_by(id=int(source_id)).first()
        if row and row.is_active:
            yield from self._chunks(row)

    @staticmethod
    def _chunks(row: Plan) -> Iterator[ChunkRecord]:
        # Bundle name + description + price so retrieval handles both
        # "what's in the course bundle" AND "how much is the plan".
        parts = [f"Plan: {row.name}"]
        if row.description:
            parts.append(row.description)
        parts.append(
            f"Bundle type: {row.bundle_type}. "
            f"Base price: {row.base_price_paise / 100:.2f} {row.currency}. "
            f"Duration: {row.duration_days} days.")
        if row.discount_price_paise:
            parts.append(
                f"Current promo price: {row.discount_price_paise / 100:.2f} "
                f"{row.currency}.")
        yield ChunkRecord(
            source_type="plan", source_id=str(row.id), chunk_index=0,
            content="\n\n".join(parts),
            metadata={"plan_name": row.name, "plan_slug": row.slug},
        )


class QuestionExplanationAdapter(SourceAdapter):
    source_type = "question_explanation"

    def iter_chunks(self, db: Session) -> Iterator[ChunkRecord]:
        for row in (db.query(Question)
                    .filter(Question.is_active.is_(True),
                            Question.explanation.is_not(None))
                    .all()):
            yield from self._chunks(row)

    def iter_chunks_for_id(self, db: Session, source_id: str
                            ) -> Iterator[ChunkRecord]:
        row = db.query(Question).filter_by(id=int(source_id)).first()
        if row and row.is_active and row.explanation:
            yield from self._chunks(row)

    @staticmethod
    def _chunks(row: Question) -> Iterator[ChunkRecord]:
        text = f"Topic: {row.domain or ''}\n\n"
        text += f"Question: {row.stem}\n\n"
        text += f"Explanation: {row.explanation}"
        yield ChunkRecord(
            source_type="question_explanation",
            source_id=str(row.id), chunk_index=0,
            content=text,
            metadata={"topic_id": row.topic_id,
                       "difficulty": row.difficulty.value if row.difficulty
                                     else None},
        )


# Registry — new adapters land here. ingest.py reads this to know what
# to walk during a full reindex.
SOURCES: dict[str, SourceAdapter] = {
    "faq":                   FAQAdapter(),
    "plan":                  PlanAdapter(),
    "question_explanation":  QuestionExplanationAdapter(),
}
