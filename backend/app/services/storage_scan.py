"""Upload linkage scan — the no-false-orphan guarantee for /admin/storage.

A file may only be trashed when NOTHING on the site references it. This
module is the single source of truth for "what references this upload":
it sweeps every column that can hold a /uploads/... URL and returns,
per path, the concrete places using it (with enough context to render
"Course → Section → Lesson" and an admin deep-link).

Reference locations swept (keep in sync with the docstring test in
tests/integration/test_storage_dashboard.py):
  1. Lesson.video_url            — lesson videos
  2. Lesson.preview_video_url    — generated free-preview clips
  3. Lesson.body_blocks (JSON)   — BlockNote image/file blocks
  4. LessonFile.file_url         — attached lesson files
  5. Course.cover_image_url      — course covers
  6. ExamSet.cover_image_url     — exam-set covers
  7. Testimonial.photo_url       — testimonial photos
  8. ContentPage.blocks (JSON)   — CMS page blocks
  9. Recording.file_url          — Zoom recording files
 10. CourseAnnouncement.body     — announcement rich text

JSON/Text sources are matched by substring on the exact /uploads/...
URL — a false POSITIVE (linked when not) only makes us refuse a
delete, which is the safe direction. System paths (invoices, RAG,
recordings dir, .trash) are classified separately and never eligible
for bulk trash.

Callers MUST re-run the scan for the specific paths at trash-action
time (`links_for_paths`) rather than trusting a listing snapshot.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.tenant import get_current_tenant_id
from app.models.content_page import ContentPage
from app.models.exam_set import ExamSet
from app.models.lms import (
    Chapter, Course, CourseAnnouncement, Lesson, LessonFile,
)
from app.models.media import MediaCandidate
from app.models.testimonial import Testimonial
from app.models.zoom import Recording

UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT", "/app/uploads"))
TRASH_DIRNAME = ".trash"

# Prefixes (relative to /uploads/) that belong to server subsystems, not
# admin content uploads. Never listed as unlinked, never bulk-trashable.
SYSTEM_PREFIXES = ("invoices/", "recordings/", TRASH_DIRNAME + "/")
SYSTEM_DIR_MARKERS = ("/rag/",)


@dataclass
class LinkRef:
    """One place an upload is used. label/course/section are for humans;
    admin_href deep-links the admin UI."""
    kind: str                       # lesson_video | lesson_preview | lesson_body | lesson_file | course_cover | exam_set_cover | testimonial_photo | content_page | zoom_file | announcement
    entity_id: int
    label: str
    course_title: str | None = None
    section_title: str | None = None
    admin_href: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LinkScan:
    """Full-tenant scan result."""
    by_path: dict[str, list[LinkRef]] = field(default_factory=dict)

    def add(self, url: str | None, ref: LinkRef) -> None:
        if not url or not url.startswith("/uploads/"):
            return
        # Normalise away any query string (signed tokens etc.).
        path = url.split("?", 1)[0]
        self.by_path.setdefault(path, []).append(ref)

    def links_for(self, path: str) -> list[LinkRef]:
        return self.by_path.get(path, [])


def is_system_path(path: str) -> bool:
    """True for uploads owned by server subsystems (invoices, Zoom
    recordings dir, RAG sources, the trash folder itself)."""
    rel = path[len("/uploads/"):] if path.startswith("/uploads/") else path
    if rel.startswith(SYSTEM_PREFIXES):
        return True
    return any(m in "/" + rel for m in SYSTEM_DIR_MARKERS)


def _urls_in_json(value) -> list[str]:
    """Every /uploads/... URL appearing anywhere inside a JSON blob."""
    found: list[str] = []
    try:
        blob = json.dumps(value)
    except (TypeError, ValueError):
        return found
    idx = 0
    while True:
        idx = blob.find("/uploads/", idx)
        if idx == -1:
            break
        end = idx
        while end < len(blob) and blob[end] not in '"\\ \n?':
            end += 1
        found.append(blob[idx:end])
        idx = end
    return found


def _urls_in_text(value: str | None) -> list[str]:
    if not value or "/uploads/" not in value:
        return []
    return _urls_in_json(value)   # same tokenizer works on plain text


def scan_links(db: Session) -> LinkScan:
    """Sweep every reference location for the current tenant. One scan
    per request — the listing endpoint calls this once and joins it
    against the filesystem walk."""
    tid = get_current_tenant_id()
    scan = LinkScan()

    # Lesson-level refs need the Course → Chapter context for labels.
    lesson_rows = (
        db.query(Lesson, Chapter.title, Course.title, Course.id)
        .join(Chapter, Lesson.chapter_id == Chapter.id)
        .join(Course, Chapter.course_id == Course.id)
        .filter(Lesson.tenant_id == tid, Lesson.is_deleted.is_(False),
                Course.is_deleted.is_(False))
        .all()
    )
    for lesson, chapter_title, course_title, _course_id in lesson_rows:
        href = f"/admin/lessons/{lesson.id}"
        ctx = dict(course_title=course_title, section_title=chapter_title,
                   admin_href=href)
        scan.add(lesson.video_url, LinkRef(
            "lesson_video", lesson.id, f"Lesson video · {lesson.title}", **ctx))
        scan.add(lesson.preview_video_url, LinkRef(
            "lesson_preview", lesson.id,
            f"Free-preview clip · {lesson.title}", **ctx))
        scan.add(lesson.thumbnail_url, LinkRef(
            "lesson_video", lesson.id, f"Lesson thumbnail · {lesson.title}", **ctx))
        for url in _urls_in_json(lesson.body_blocks):
            scan.add(url, LinkRef(
                "lesson_body", lesson.id,
                f"Lesson content · {lesson.title}", **ctx))

    file_rows = (
        db.query(LessonFile, Lesson.title, Chapter.title, Course.title)
        .join(Lesson, LessonFile.lesson_id == Lesson.id)
        .join(Chapter, Lesson.chapter_id == Chapter.id)
        .join(Course, Chapter.course_id == Course.id)
        .filter(LessonFile.tenant_id == tid, Lesson.is_deleted.is_(False))
        .all()
    )
    for lf, lesson_title, chapter_title, course_title in file_rows:
        scan.add(lf.file_url, LinkRef(
            "lesson_file", lf.lesson_id,
            f"Lesson file · {lf.filename} ({lesson_title})",
            course_title=course_title, section_title=chapter_title,
            admin_href=f"/admin/lessons/{lf.lesson_id}"))

    for c in (db.query(Course)
              .filter(Course.tenant_id == tid, Course.is_deleted.is_(False))):
        scan.add(c.cover_image_url, LinkRef(
            "course_cover", c.id, f"Course cover · {c.title}",
            course_title=c.title, admin_href=f"/admin/courses/{c.id}"))

    for es in db.query(ExamSet):   # ExamSet has no tenant column
        scan.add(es.cover_image_url, LinkRef(
            "exam_set_cover", es.id, f"Exam-set cover · {es.name}",
            admin_href=f"/admin/exam-sets/{es.id}"))

    for t in db.query(Testimonial):
        scan.add(t.photo_url, LinkRef(
            "testimonial_photo", t.id, f"Testimonial photo · {t.name}",
            admin_href="/admin/testimonials"))

    for p in (db.query(ContentPage)
              .filter(ContentPage.tenant_id == tid,
                      ContentPage.is_deleted.is_(False))):
        for url in _urls_in_json(p.blocks):
            scan.add(url, LinkRef(
                "content_page", p.id, f"Page · {p.title}",
                admin_href=f"/admin/content-pages/{p.id}"))

    for r in db.query(Recording).filter(Recording.tenant_id == tid):
        scan.add(r.file_url, LinkRef(
            "zoom_file", r.id, f"Zoom recording #{r.id}",
            admin_href="/admin/live-classes"))

    ann_rows = (
        db.query(CourseAnnouncement, Course.title)
        .join(Course, CourseAnnouncement.course_id == Course.id)
        .filter(CourseAnnouncement.tenant_id == tid)
        .all()
    )
    for ann, course_title in ann_rows:
        for url in _urls_in_text(ann.body):
            scan.add(url, LinkRef(
                "announcement", ann.id, f"Announcement · {ann.title}",
                course_title=course_title,
                admin_href=f"/admin/courses/{ann.course_id}"))

    # Pending candidates keep their FILES referenced (candidate output +
    # its parent) so neither shows as deletable while a decision is open.
    for mc in (db.query(MediaCandidate)
               .filter(MediaCandidate.tenant_id == tid,
                       MediaCandidate.status == "pending")):
        scan.add(mc.candidate_path, LinkRef(
            "candidate", mc.id, "Compressed candidate (pending decision)",
            admin_href="/admin/storage"))
        scan.add(mc.parent_path, LinkRef(
            "candidate_parent", mc.id,
            "Original of a pending compressed candidate",
            admin_href="/admin/storage"))

    return scan


def links_for_paths(db: Session, paths: list[str]) -> dict[str, list[LinkRef]]:
    """Action-time re-verification: fresh scan, filtered to ``paths``.
    Used by POST /admin/storage/trash so a stale listing can never
    delete something that became linked after the page loaded."""
    scan = scan_links(db)
    return {p: scan.links_for(p.split("?", 1)[0]) for p in paths}
