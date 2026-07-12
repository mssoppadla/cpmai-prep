"""Source adapters for the assistant's site-wide knowledge.

Pins the three adapters added in July 2026 (course catalog, CMS
content pages, live Zoom sessions):

  * visibility filters — drafts / deleted / gated content NEVER reach
    the corpus (the chat is open to anonymous visitors)
  * chunk content includes the facts the assistant must answer with
    (prices, dates, outcomes)
  * BlockNote JSON flattening survives odd shapes without raising
  * SOURCES registry exposes every adapter to full reindex
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.content_page import ContentPage
from app.models.lms import Course
from app.models.zoom import ZoomSession
from app.services.assistant.rag.sources import (
    SOURCES, ContentPageAdapter, CourseAdapter, ZoomSessionAdapter,
    _blocknote_text,
)


def test_sources_registry_has_sitewide_types():
    for t in ("course", "content_page", "zoom_session"):
        assert t in SOURCES, f"{t} missing from SOURCES registry"
        assert SOURCES[t].source_type == t


# ============================================================ courses

def _course(db, **kw):
    c = Course(slug=kw.pop("slug", "cpmai-fundamentals"),
               title=kw.pop("title", "CPMAI Fundamentals"),
               is_published=kw.pop("is_published", True),
               **kw)
    db.add(c); db.commit(); db.refresh(c)
    return c


def test_course_adapter_indexes_published_with_price_and_outcomes(db):
    c = _course(db, subtitle="Master the 6 phases",
                description="Deep dive into the methodology.",
                base_price_paise=499900, currency="INR",
                estimated_hours=12,
                learning_outcomes=["Understand Phase I", "Run a pilot"])
    chunks = list(CourseAdapter().iter_chunks_for_id(db, str(c.id)))
    assert len(chunks) == 1
    text = chunks[0].content
    assert "CPMAI Fundamentals" in text
    assert "4999.00 INR" in text
    assert "12 hours" in text
    assert "Understand Phase I" in text
    assert chunks[0].metadata["course_slug"] == "cpmai-fundamentals"


def test_course_adapter_free_course_says_free(db):
    c = _course(db, slug="free-intro", title="Free Intro",
                enrollment_type="free", base_price_paise=0)
    (chunk,) = CourseAdapter().iter_chunks_for_id(db, str(c.id))
    assert "free to enrol" in chunk.content


def test_course_adapter_skips_drafts_and_deleted(db):
    draft = _course(db, slug="draft-course", title="Draft", is_published=False)
    gone = _course(db, slug="gone-course", title="Gone", is_deleted=True)
    assert list(CourseAdapter().iter_chunks_for_id(db, str(draft.id))) == []
    assert list(CourseAdapter().iter_chunks_for_id(db, str(gone.id))) == []
    indexed_ids = {c.source_id for c in CourseAdapter().iter_chunks(db)}
    assert str(draft.id) not in indexed_ids
    assert str(gone.id) not in indexed_ids


# ============================================================ content pages

_BLOCKS = [
    {"type": "heading", "content": [{"type": "text", "text": "Study guide"}]},
    {"type": "paragraph",
     "content": [{"type": "text", "text": "Read the "},
                  {"type": "link",
                   "content": [{"type": "text", "text": "ECO outline"}]},
                  {"type": "text", "text": " first."}],
     "children": [
         {"type": "paragraph",
          "content": [{"type": "text", "text": "Nested tip."}]},
     ]},
]


def test_blocknote_flattener_handles_links_children_and_junk():
    text = _blocknote_text(_BLOCKS + [None, "junk", {"content": 42}])
    assert "Study guide" in text
    assert "Read the ECO outline first." in text
    assert "Nested tip." in text


def _page(db, **kw):
    p = ContentPage(slug=kw.pop("slug", "study-guide"),
                    title=kw.pop("title", "CPMAI Study Guide"),
                    blocks=kw.pop("blocks", _BLOCKS),
                    is_published=kw.pop("is_published", True),
                    nav_visibility=kw.pop("nav_visibility", "always"),
                    **kw)
    db.add(p); db.commit(); db.refresh(p)
    return p


def test_content_page_adapter_indexes_public_published_pages(db):
    p = _page(db)
    chunks = list(ContentPageAdapter().iter_chunks_for_id(db, str(p.id)))
    assert chunks
    assert chunks[0].content.startswith("Page: CPMAI Study Guide")
    assert "Nested tip." in "".join(c.content for c in chunks)
    assert chunks[0].metadata["page_slug"] == "study-guide"


def test_content_page_adapter_never_leaks_gated_or_draft_pages(db):
    gated = _page(db, slug="member-notes", nav_visibility="authenticated")
    draft = _page(db, slug="wip", is_published=False)
    hidden = _page(db, slug="secret", nav_visibility="hidden")
    for row in (gated, draft, hidden):
        assert list(ContentPageAdapter().iter_chunks_for_id(db, str(row.id))) == []
    indexed = {c.source_id for c in ContentPageAdapter().iter_chunks(db)}
    assert {str(gated.id), str(draft.id), str(hidden.id)} & indexed == set()


def test_content_page_adapter_chunks_long_pages_with_title_prefix(db):
    long_blocks = [
        {"type": "paragraph",
         "content": [{"type": "text", "text": f"Paragraph {i} " + "x" * 300}]}
        for i in range(12)
    ]
    p = _page(db, slug="long-page", title="Long Page", blocks=long_blocks)
    chunks = list(ContentPageAdapter().iter_chunks_for_id(db, str(p.id)))
    assert len(chunks) > 1
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.content.startswith("Page: Long Page") for c in chunks)


# ============================================================ zoom sessions

def _session(db, **kw):
    s = ZoomSession(title=kw.pop("title", "Phase III deep dive"),
                    scheduled_at=kw.pop(
                        "scheduled_at",
                        datetime(2026, 8, 1, 14, 30, tzinfo=timezone.utc)),
                    status=kw.pop("status", "scheduled"),
                    **kw)
    db.add(s); db.commit(); db.refresh(s)
    return s


def test_zoom_adapter_spells_out_the_date_and_never_join_urls(db):
    s = _session(db, description="Live walkthrough",
                 duration_minutes=90,
                 zoom_join_url="https://zoom.us/j/secret",
                 zoom_start_url="https://zoom.us/s/secret")
    (chunk,) = ZoomSessionAdapter().iter_chunks_for_id(db, str(s.id))
    assert "Phase III deep dive" in chunk.content
    assert "Saturday, 01 August 2026 at 14:30 UTC" in chunk.content
    assert "90 minutes" in chunk.content
    assert "secret" not in chunk.content          # join URLs never leak
    assert chunk.metadata["scheduled_at"].startswith("2026-08-01T14:30")


def test_zoom_adapter_only_scheduled_or_live(db):
    draft = _session(db, title="Draft", status="draft")
    ended = _session(db, title="Ended", status="ended")
    cancelled = _session(db, title="Cancelled", status="cancelled")
    live = _session(db, title="Live now", status="live")
    for row in (draft, ended, cancelled):
        assert list(ZoomSessionAdapter().iter_chunks_for_id(db, str(row.id))) == []
    assert list(ZoomSessionAdapter().iter_chunks_for_id(db, str(live.id)))


def test_zoom_adapter_names_the_linked_course(db):
    c = _course(db, slug="linked", title="Linked Course")
    s = _session(db, course_id=c.id)
    (chunk,) = ZoomSessionAdapter().iter_chunks_for_id(db, str(s.id))
    assert "Part of the course: Linked Course." in chunk.content
