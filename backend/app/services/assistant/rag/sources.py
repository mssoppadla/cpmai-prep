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
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy.orm import Session

from app.models.content_page import ContentPage
from app.models.faq import FaqItem
from app.models.lms import Course
from app.models.plan import Plan
from app.models.question import Question
from app.models.rag_chunk import RagChunk
from app.models.zoom import ZoomSession


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


class UploadAdapter(SourceAdapter):
    """Admin-uploaded files (.txt/.md/.pdf/.docx/.xlsx).

    Unique among adapters: there's no domain source row to re-derive
    chunks from — the raw bytes aren't kept after the upload endpoint
    parses + embeds them. So iter_chunks re-yields what's already in
    rag_chunks, which lets a future model-swap reindex re-embed in
    place without forcing the admin to re-upload every file.

    source_id == str(RagDocument.id).
    """
    source_type = "upload"

    def iter_chunks(self, db: Session) -> Iterator[ChunkRecord]:
        rows = (db.query(RagChunk)
                .filter(RagChunk.source_type == "upload")
                .order_by(RagChunk.source_id, RagChunk.chunk_index)
                .all())
        for r in rows:
            yield ChunkRecord(
                source_type="upload",
                source_id=r.source_id,
                chunk_index=r.chunk_index,
                content=r.content,
                metadata=r.chunk_metadata or {},
            )

    def iter_chunks_for_id(self, db: Session, source_id: str
                            ) -> Iterator[ChunkRecord]:
        rows = (db.query(RagChunk)
                .filter(RagChunk.source_type == "upload",
                        RagChunk.source_id == source_id)
                .order_by(RagChunk.chunk_index)
                .all())
        for r in rows:
            yield ChunkRecord(
                source_type="upload",
                source_id=r.source_id,
                chunk_index=r.chunk_index,
                content=r.content,
                metadata=r.chunk_metadata or {},
            )


class CourseAdapter(SourceAdapter):
    """Published course catalog — title, description, outcomes, price.

    Lets the assistant answer "what courses do you offer", "what does
    the fundamentals course cover", "how much is the course", with a
    deep link to /courses/{slug}. Only published, non-deleted courses
    are indexed (drafts stay admin-only).
    """
    source_type = "course"

    def iter_chunks(self, db: Session) -> Iterator[ChunkRecord]:
        rows = (db.query(Course)
                .filter(Course.is_published.is_(True),
                        Course.is_deleted.is_(False))
                .all())
        for row in rows:
            yield from self._chunks(row)

    def iter_chunks_for_id(self, db: Session, source_id: str
                            ) -> Iterator[ChunkRecord]:
        row = db.query(Course).filter_by(id=int(source_id)).first()
        if row and row.is_published and not row.is_deleted:
            yield from self._chunks(row)

    @staticmethod
    def _chunks(row: Course) -> Iterator[ChunkRecord]:
        parts = [f"Course: {row.title}"]
        if row.subtitle:
            parts.append(row.subtitle)
        if row.description:
            parts.append(row.description[:2000])
        facts = [f"Difficulty: {row.difficulty}."]
        if row.estimated_hours:
            facts.append(f"Estimated effort: {row.estimated_hours} hours.")
        if row.enrollment_type == "free" or not row.base_price_paise:
            facts.append("Price: free to enrol.")
        else:
            facts.append(
                f"Price: {row.base_price_paise / 100:.2f} {row.currency} "
                "(see /pricing for bundles and current offers).")
        parts.append(" ".join(facts))
        outcomes = [o for o in (row.learning_outcomes or [])
                    if isinstance(o, str) and o.strip()]
        if outcomes:
            parts.append("What you will learn: " + "; ".join(outcomes[:12]))
        if row.prerequisites_text:
            parts.append(f"Prerequisites: {row.prerequisites_text[:500]}")
        if row.target_audience:
            parts.append(f"Who it's for: {row.target_audience[:500]}")
        yield ChunkRecord(
            source_type="course", source_id=str(row.id), chunk_index=0,
            content="\n\n".join(parts),
            metadata={"course_title": row.title, "course_slug": row.slug},
        )


def _blocknote_text(blocks: list) -> str:
    """Flatten a BlockNote JSON document to plain text.

    Blocks are {type, content: [inline...], children: [block...]} where
    inline nodes carry "text" (plain runs) or nest their own "content"
    (links). Defensive on shape — the server treats blocks as opaque
    JSON, so anything unrecognised is skipped, never raised on.
    """
    lines: list[str] = []

    def inline_text(nodes) -> str:
        out: list[str] = []
        for n in nodes if isinstance(nodes, list) else []:
            if not isinstance(n, dict):
                continue
            if isinstance(n.get("text"), str):
                out.append(n["text"])
            elif n.get("content") is not None:
                out.append(inline_text(n["content"]))
        return "".join(out)

    def walk(block_list) -> None:
        for b in block_list if isinstance(block_list, list) else []:
            if not isinstance(b, dict):
                continue
            content = b.get("content")
            # Table blocks nest rows under content.rows[].cells[][].
            if isinstance(content, dict):
                for row in content.get("rows", []) or []:
                    cells = row.get("cells", []) if isinstance(row, dict) else []
                    cell_texts = [inline_text(c) for c in cells]
                    if any(cell_texts):
                        lines.append(" | ".join(cell_texts))
            else:
                text = inline_text(content)
                if text.strip():
                    lines.append(text.strip())
            walk(b.get("children"))

    walk(blocks)
    return "\n".join(lines)


class ContentPageAdapter(SourceAdapter):
    """Published, PUBLICLY-visible CMS pages (study guide, about, ...).

    Only ``nav_visibility="always"`` pages are indexed — the chat is
    open to anonymous visitors, so authenticated/subscribed-gated page
    content must not leak through citations. Long pages are split into
    ~1500-char chunks so retrieval stays precise.
    """
    source_type = "content_page"

    _CHUNK_CHARS = 1500

    def iter_chunks(self, db: Session) -> Iterator[ChunkRecord]:
        rows = (db.query(ContentPage)
                .filter(ContentPage.is_published.is_(True),
                        ContentPage.is_deleted.is_(False),
                        ContentPage.nav_visibility == "always")
                .all())
        for row in rows:
            yield from self._chunks(row)

    def iter_chunks_for_id(self, db: Session, source_id: str
                            ) -> Iterator[ChunkRecord]:
        row = db.query(ContentPage).filter_by(id=int(source_id)).first()
        if (row and row.is_published and not row.is_deleted
                and row.nav_visibility == "always"):
            yield from self._chunks(row)

    @classmethod
    def _chunks(cls, row: ContentPage) -> Iterator[ChunkRecord]:
        body = _blocknote_text(row.blocks or [])
        if not body.strip():
            return
        # Greedy line-packing into ~1500-char chunks; every chunk is
        # prefixed with the page title so retrieval + citations stay
        # self-describing even for chunk 3 of a long page.
        buf: list[str] = []
        size = 0
        idx = 0
        for line in body.split("\n"):
            if size + len(line) > cls._CHUNK_CHARS and buf:
                yield ChunkRecord(
                    source_type="content_page", source_id=str(row.id),
                    chunk_index=idx,
                    content=f"Page: {row.title}\n\n" + "\n".join(buf),
                    metadata={"page_title": row.title, "page_slug": row.slug},
                )
                idx += 1
                buf, size = [], 0
            buf.append(line)
            size += len(line) + 1
        if buf:
            yield ChunkRecord(
                source_type="content_page", source_id=str(row.id),
                chunk_index=idx,
                content=f"Page: {row.title}\n\n" + "\n".join(buf),
                metadata={"page_title": row.title, "page_slug": row.slug},
            )


class ZoomSessionAdapter(SourceAdapter):
    """Upcoming/live Zoom classes — title, DATE, duration, course link.

    Indexes only ``scheduled``/``live`` sessions (drafts are invisible,
    ended/cancelled drop out on the next reindex). Public-safe fields
    only — never the join/start URLs. The chunk text spells out the
    date in words so "when is the next live class" retrieves well; the
    agentic ``live_sessions`` tool complements this with an always-
    fresh DB read.
    """
    source_type = "zoom_session"

    def iter_chunks(self, db: Session) -> Iterator[ChunkRecord]:
        rows = (db.query(ZoomSession)
                .filter(ZoomSession.status.in_(("scheduled", "live")),
                        ZoomSession.is_deleted.is_(False))
                .order_by(ZoomSession.scheduled_at)
                .all())
        for row in rows:
            yield from self._chunks(row, db)

    def iter_chunks_for_id(self, db: Session, source_id: str
                            ) -> Iterator[ChunkRecord]:
        row = db.query(ZoomSession).filter_by(id=int(source_id)).first()
        if (row and row.status in ("scheduled", "live")
                and not row.is_deleted):
            yield from self._chunks(row, db)

    @staticmethod
    def _chunks(row: ZoomSession, db: Session) -> Iterator[ChunkRecord]:
        when = row.scheduled_at
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when_text = (when.strftime("%A, %d %B %Y at %H:%M UTC")
                     if when else "date to be announced")
        parts = [
            f"Live class session: {row.title}",
            f"Scheduled for {when_text}. "
            f"Duration: {row.duration_minutes} minutes. "
            f"Status: {row.status}.",
        ]
        if row.description:
            parts.append(row.description[:800])
        if row.course_id:
            course = db.query(Course).filter_by(id=row.course_id).first()
            if course:
                parts.append(f"Part of the course: {course.title}.")
        parts.append(
            "Joining requires an enrolled/subscribed account; sign in "
            "and open the dashboard to join when the session is live.")
        yield ChunkRecord(
            source_type="zoom_session", source_id=str(row.id), chunk_index=0,
            content="\n\n".join(parts),
            metadata={"session_title": row.title,
                       "scheduled_at": when.isoformat() if when else None,
                       "course_id": row.course_id},
        )


# Registry — new adapters land here. ingest.py reads this to know what
# to walk during a full reindex.
SOURCES: dict[str, SourceAdapter] = {
    "faq":                   FAQAdapter(),
    "plan":                  PlanAdapter(),
    "question_explanation":  QuestionExplanationAdapter(),
    "upload":                UploadAdapter(),
    "course":                CourseAdapter(),
    "content_page":          ContentPageAdapter(),
    "zoom_session":          ZoomSessionAdapter(),
}
