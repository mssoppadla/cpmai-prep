"""Admin LMS endpoints — courses, chapters, lessons, files, enrollments,
categories, announcements, quizzes.

All gated by ``get_admin_user`` at the parent router level. Every
write emits an audit_log entry. Tenant scope is enforced via
``get_current_tenant_id()`` on every query (contract I-3 + I-4).

Endpoint groups (router suffixes documented at the bottom):
  /courses                   — CRUD + reorder
  /courses/{id}/chapters     — chapter CRUD (nested)
  /chapters/{id}             — chapter detail + delete
  /chapters/{id}/lessons     — lesson CRUD (nested)
  /lessons/{id}              — lesson detail + delete
  /lessons/{id}/files        — file CRUD
  /courses/{id}/enrollments  — list / grant
  /enrollments/{id}          — revoke
  /courses/{id}/announcements — CRUD
  /course-categories         — CRUD
  /quizzes/{lesson_id}       — upsert config + questions + options
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.tenant import get_current_tenant_id
from app.models.lms import (
    Chapter, Course, CourseAnnouncement, CourseCategory,
    CourseCategoryLink, Enrollment, Lesson, LessonFile,
    LmsQuiz, LmsQuizQuestion, LmsQuizQuestionOption,
)
from app.models.user import User
from app.schemas.lms import (
    ChapterCreateIn, ChapterOut, ChapterUpdateIn,
    CourseAnnouncementCreateIn, CourseAnnouncementOut,
    CourseCategoryCreateIn, CourseCategoryOut, CourseCategoryUpdateIn,
    CourseCreateIn, CourseOut, CourseUpdateIn,
    EnrollmentGrantIn, EnrollmentOut,
    LessonCreateIn, LessonFileCreateIn, LessonFileOut, LessonOut,
    LessonUpdateIn,
    QuizConfigUpsertIn, QuizOptionCreateIn, QuizOptionOut,
    QuizOptionUpdateIn, QuizOut, QuizQuestionCreateIn, QuizQuestionOut,
    QuizQuestionUpdateIn,
)


router = APIRouter()
log = logging.getLogger(__name__)


# Local-disk uploads root — kept in sync with admin/uploads.py + main.py.
# Re-derived here from the env so a future R2 swap (file_object_key path)
# only has to change admin/uploads.py + this constant. The lesson-file
# delete endpoint uses this to unlink the underlying file when the row
# is removed; without that, /app/uploads grows unboundedly across the
# course's lifetime.
_UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT", "/app/uploads"))


def _unlink_local_upload(file_url: str | None) -> None:
    """Best-effort delete of the on-disk file backing a LessonFile row.

    Quiet on missing files (already deleted, or never existed) — the DB
    row delete is the authoritative action and we don't want a stray
    filesystem hiccup to fail the API request.

    External URLs (anything that doesn't start with /uploads/) are
    skipped: the admin may have pasted a Vimeo / S3 / YouTube URL into
    file_url for an externally-hosted asset, and we have no business
    touching that.
    """
    if not file_url or not file_url.startswith("/uploads/"):
        return
    # /uploads/1/2026/05/abc-file.pdf → 1/2026/05/abc-file.pdf
    rel = file_url[len("/uploads/"):].lstrip("/")
    # Resolve + verify the result is INSIDE UPLOAD_ROOT before unlinking,
    # to defeat any "../" path-traversal that slipped past the upload
    # sanitiser. Defense-in-depth; the upload endpoint already prevents
    # this, but a row could have been created via a future bulk-import.
    try:
        abs_path = (_UPLOAD_ROOT / rel).resolve()
        upload_root_resolved = _UPLOAD_ROOT.resolve()
    except OSError:
        log.warning("could not resolve upload path for %s", file_url)
        return
    try:
        abs_path.relative_to(upload_root_resolved)
    except ValueError:
        log.warning("refusing to unlink file outside UPLOAD_ROOT: %s", file_url)
        return
    try:
        abs_path.unlink(missing_ok=True)
    except OSError as e:
        log.warning("unlink %s failed: %s (row still deleted)", abs_path, e)


# ============================================================ helpers

def _course_scope(db: Session):
    """Base course query: tenant + non-deleted."""
    return db.query(Course).filter(
        Course.tenant_id == get_current_tenant_id(),
        Course.is_deleted.is_(False),
    )


def _course_slug_taken(db: Session, slug: str, exclude_id: int | None = None) -> bool:
    q = db.query(Course.id).filter(
        Course.tenant_id == get_current_tenant_id(),
        Course.slug == slug,
        Course.is_deleted.is_(False),
    )
    if exclude_id is not None:
        q = q.filter(Course.id != exclude_id)
    return db.query(q.exists()).scalar()


# ============================================================ COURSES

@router.get("/courses", response_model=list[CourseOut])
def list_courses(
    db: Session = Depends(get_db),
    include_unpublished: bool = Query(True),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    q = _course_scope(db)
    if not include_unpublished:
        q = q.filter(Course.is_published.is_(True))
    return (q.order_by(Course.display_order, Course.id)
            .offset(offset).limit(limit).all())


@router.get("/courses/{course_id}", response_model=CourseOut)
def get_course(course_id: int, db: Session = Depends(get_db)):
    c = _course_scope(db).filter(Course.id == course_id).first()
    if not c:
        raise NotFoundError("Course not found")
    return c


@router.get("/courses/{course_id}/tree")
def get_course_tree(course_id: int, db: Session = Depends(get_db)):
    """Admin curriculum tree for a course — chapters + lessons + files,
    including unpublished/draft rows. Used by /admin/courses/[id] in the
    UI so editing works before the course is published.

    Returns:
      { course: {...full admin payload...},
        chapters: [
          { id, title, description, position, is_mandatory, is_published,
            lessons: [
              { id, title, lesson_type, position, is_mandatory,
                is_free_preview, is_published, duration_seconds, ...,
                files: [ {...LessonFileOut...} ] }
            ] }
        ] }
    """
    c = _course_scope(db).filter(Course.id == course_id).first()
    if not c:
        raise NotFoundError("Course not found")

    chapters = list(db.query(Chapter).filter(
        Chapter.course_id == c.id,
        Chapter.tenant_id == get_current_tenant_id(),
        Chapter.is_deleted.is_(False),
    ).order_by(Chapter.position, Chapter.id).all())

    lessons_by_ch: dict[int, list[Lesson]] = {ch.id: [] for ch in chapters}
    if chapters:
        for lsn in db.query(Lesson).filter(
            Lesson.chapter_id.in_([ch.id for ch in chapters]),
            Lesson.is_deleted.is_(False),
        ).order_by(Lesson.chapter_id, Lesson.position).all():
            lessons_by_ch.setdefault(lsn.chapter_id, []).append(lsn)

    lesson_ids = [l.id for ls in lessons_by_ch.values() for l in ls]
    files_by_lesson: dict[int, list[LessonFile]] = {}
    if lesson_ids:
        for f in db.query(LessonFile).filter(
            LessonFile.lesson_id.in_(lesson_ids),
            LessonFile.tenant_id == get_current_tenant_id(),
        ).order_by(LessonFile.position).all():
            files_by_lesson.setdefault(f.lesson_id, []).append(f)

    return {
        "course": CourseOut.model_validate(c).model_dump(mode="json"),
        "chapters": [
            {
                **ChapterOut.model_validate(ch).model_dump(mode="json"),
                "lessons": [
                    {
                        **LessonOut.model_validate(lsn).model_dump(mode="json"),
                        "files": [
                            LessonFileOut.model_validate(f).model_dump(mode="json")
                            for f in files_by_lesson.get(lsn.id, [])
                        ],
                    }
                    for lsn in lessons_by_ch.get(ch.id, [])
                ],
            }
            for ch in chapters
        ],
    }


@router.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: int, db: Session = Depends(get_db)):
    """Admin single-lesson getter. Replaces the previous PATCH-no-op
    hack the frontend was using to load a lesson on first open.

    Adds ``course_id`` to the response (sourced via chapter→course join)
    so the lesson editor can render a correct "← Back to course" link
    without an additional round-trip.
    """
    lsn = db.query(Lesson).filter(
        Lesson.id == lesson_id,
        Lesson.tenant_id == get_current_tenant_id(),
        Lesson.is_deleted.is_(False),
    ).first()
    if not lsn:
        raise NotFoundError("Lesson not found")
    ch = db.get(Chapter, lsn.chapter_id)
    return {
        **LessonOut.model_validate(lsn).model_dump(mode="json"),
        "course_id": ch.course_id if ch else None,
    }


@router.get("/lessons/{lesson_id}/files", response_model=list[LessonFileOut])
def list_lesson_files(lesson_id: int, db: Session = Depends(get_db)):
    """Admin lesson-files listing — for the editor's Attached Files panel."""
    return (db.query(LessonFile).filter(
        LessonFile.lesson_id == lesson_id,
        LessonFile.tenant_id == get_current_tenant_id(),
    ).order_by(LessonFile.position, LessonFile.id).all())


@router.post("/courses", response_model=CourseOut, status_code=201)
def create_course(
    payload: CourseCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    if _course_slug_taken(db, payload.slug):
        raise ConflictError(f"A course with slug '{payload.slug}' already exists.")
    c = Course(
        tenant_id=get_current_tenant_id(),
        created_by=admin.id,
        **payload.model_dump(),
    )
    db.add(c); db.commit(); db.refresh(c)
    audit_log(db, admin.id, "course.created",
              {"id": c.id, "slug": c.slug, "title": c.title})
    return c


@router.patch("/courses/{course_id}", response_model=CourseOut)
def update_course(
    course_id: int,
    payload: CourseUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    c = _course_scope(db).filter(Course.id == course_id).first()
    if not c:
        raise NotFoundError("Course not found")
    updates = payload.model_dump(exclude_unset=True)
    new_slug = updates.get("slug")
    if new_slug and new_slug != c.slug:
        if _course_slug_taken(db, new_slug, exclude_id=c.id):
            raise ConflictError(f"A course with slug '{new_slug}' already exists.")
    for k, v in updates.items():
        setattr(c, k, v)
    db.commit(); db.refresh(c)
    audit_log(db, admin.id, "course.updated",
              {"id": c.id, "slug": c.slug, "changed": sorted(updates.keys())})
    return c


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    c = _course_scope(db).filter(Course.id == course_id).first()
    if not c:
        raise NotFoundError("Course not found")
    c.is_deleted = True
    c.deleted_at = datetime.now(timezone.utc)
    c.deleted_by = admin.id
    db.commit()
    audit_log(db, admin.id, "course.deleted", {"id": c.id, "slug": c.slug})


# ============================================================ CHAPTERS

@router.post("/courses/{course_id}/chapters", response_model=ChapterOut, status_code=201)
def create_chapter(
    course_id: int,
    payload: ChapterCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    c = _course_scope(db).filter(Course.id == course_id).first()
    if not c:
        raise NotFoundError("Course not found")
    # Auto-assign position to end of list if not specified meaningfully
    position = payload.position
    if position == 0:
        max_pos = db.execute(
            select(Chapter.position).where(
                Chapter.course_id == c.id,
                Chapter.is_deleted.is_(False),
            ).order_by(Chapter.position.desc()).limit(1)
        ).scalar() or 0
        position = max_pos + 10
    ch = Chapter(
        tenant_id=get_current_tenant_id(),
        course_id=c.id,
        title=payload.title,
        description=payload.description,
        position=position,
        is_mandatory=payload.is_mandatory,
        is_published=payload.is_published,
    )
    db.add(ch); db.commit(); db.refresh(ch)
    audit_log(db, admin.id, "chapter.created",
              {"id": ch.id, "course_id": c.id, "title": ch.title})
    return ch


@router.patch("/chapters/{chapter_id}", response_model=ChapterOut)
def update_chapter(
    chapter_id: int,
    payload: ChapterUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    ch = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.tenant_id == get_current_tenant_id(),
        Chapter.is_deleted.is_(False),
    ).first()
    if not ch:
        raise NotFoundError("Chapter not found")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(ch, k, v)
    db.commit(); db.refresh(ch)
    audit_log(db, admin.id, "chapter.updated",
              {"id": ch.id, "changed": sorted(updates.keys())})
    return ch


@router.delete("/chapters/{chapter_id}", status_code=204)
def delete_chapter(
    chapter_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    ch = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.tenant_id == get_current_tenant_id(),
        Chapter.is_deleted.is_(False),
    ).first()
    if not ch:
        raise NotFoundError("Chapter not found")
    ch.is_deleted = True
    ch.deleted_at = datetime.now(timezone.utc)
    ch.deleted_by = admin.id
    db.commit()
    audit_log(db, admin.id, "chapter.deleted", {"id": ch.id})


# ============================================================ LESSONS

@router.post("/chapters/{chapter_id}/lessons", response_model=LessonOut, status_code=201)
def create_lesson(
    chapter_id: int,
    payload: LessonCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    ch = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.tenant_id == get_current_tenant_id(),
        Chapter.is_deleted.is_(False),
    ).first()
    if not ch:
        raise NotFoundError("Chapter not found")
    position = payload.position
    if position == 0:
        max_pos = db.execute(
            select(Lesson.position).where(
                Lesson.chapter_id == ch.id,
                Lesson.is_deleted.is_(False),
            ).order_by(Lesson.position.desc()).limit(1)
        ).scalar() or 0
        position = max_pos + 10
    data = payload.model_dump()
    data["position"] = position
    lsn = Lesson(
        tenant_id=get_current_tenant_id(),
        chapter_id=ch.id,
        **data,
    )
    db.add(lsn); db.commit(); db.refresh(lsn)
    audit_log(db, admin.id, "lesson.created",
              {"id": lsn.id, "chapter_id": ch.id, "type": lsn.lesson_type})
    return lsn


@router.patch("/lessons/{lesson_id}", response_model=LessonOut)
def update_lesson(
    lesson_id: int,
    payload: LessonUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    lsn = db.query(Lesson).filter(
        Lesson.id == lesson_id,
        Lesson.tenant_id == get_current_tenant_id(),
        Lesson.is_deleted.is_(False),
    ).first()
    if not lsn:
        raise NotFoundError("Lesson not found")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(lsn, k, v)
    db.commit(); db.refresh(lsn)
    audit_log(db, admin.id, "lesson.updated",
              {"id": lsn.id, "changed": sorted(updates.keys())})
    return lsn


@router.delete("/lessons/{lesson_id}", status_code=204)
def delete_lesson(
    lesson_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    lsn = db.query(Lesson).filter(
        Lesson.id == lesson_id,
        Lesson.tenant_id == get_current_tenant_id(),
        Lesson.is_deleted.is_(False),
    ).first()
    if not lsn:
        raise NotFoundError("Lesson not found")
    lsn.is_deleted = True
    lsn.deleted_at = datetime.now(timezone.utc)
    lsn.deleted_by = admin.id
    db.commit()
    audit_log(db, admin.id, "lesson.deleted", {"id": lsn.id})


# ============================================================ LESSON FILES

@router.post("/lessons/{lesson_id}/files", response_model=LessonFileOut, status_code=201)
def add_lesson_file(
    lesson_id: int,
    payload: LessonFileCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    lsn = db.query(Lesson).filter(
        Lesson.id == lesson_id,
        Lesson.tenant_id == get_current_tenant_id(),
        Lesson.is_deleted.is_(False),
    ).first()
    if not lsn:
        raise NotFoundError("Lesson not found")
    f = LessonFile(
        tenant_id=get_current_tenant_id(),
        lesson_id=lsn.id,
        uploaded_by_id=admin.id,
        **payload.model_dump(),
    )
    db.add(f); db.commit(); db.refresh(f)
    audit_log(db, admin.id, "lesson_file.added",
              {"id": f.id, "lesson_id": lsn.id, "filename": f.filename})
    return f


@router.delete("/lesson-files/{file_id}", status_code=204)
def delete_lesson_file(
    file_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    f = db.query(LessonFile).filter(
        LessonFile.id == file_id,
        LessonFile.tenant_id == get_current_tenant_id(),
    ).first()
    if not f:
        raise NotFoundError("File not found")
    # Capture the URL BEFORE the row is gone — the unlink helper needs
    # it to resolve the on-disk path.
    file_url = f.file_url
    db.delete(f); db.commit()
    _unlink_local_upload(file_url)
    audit_log(db, admin.id, "lesson_file.deleted", {"id": file_id, "url": file_url})


# ============================================================ ENROLLMENTS

@router.get("/courses/{course_id}/enrollments", response_model=list[EnrollmentOut])
def list_course_enrollments(
    course_id: int,
    db: Session = Depends(get_db),
    include_revoked: bool = Query(False),
):
    c = _course_scope(db).filter(Course.id == course_id).first()
    if not c:
        raise NotFoundError("Course not found")
    q = db.query(Enrollment).filter(
        Enrollment.course_id == c.id,
        Enrollment.tenant_id == get_current_tenant_id(),
    )
    if not include_revoked:
        q = q.filter(Enrollment.revoked_at.is_(None))
    return q.order_by(Enrollment.enrolled_at.desc()).all()


@router.post("/courses/{course_id}/enrollments", response_model=EnrollmentOut, status_code=201)
def grant_enrollment(
    course_id: int,
    payload: EnrollmentGrantIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    c = _course_scope(db).filter(Course.id == course_id).first()
    if not c:
        raise NotFoundError("Course not found")
    target = db.get(User, payload.user_id)
    if not target:
        raise NotFoundError("User not found")
    # Block double-active enrollment
    existing = db.query(Enrollment).filter(
        Enrollment.user_id == target.id,
        Enrollment.course_id == c.id,
        Enrollment.revoked_at.is_(None),
    ).first()
    if existing:
        raise ConflictError("User is already enrolled in this course.")
    e = Enrollment(
        tenant_id=get_current_tenant_id(),
        user_id=target.id,
        course_id=c.id,
        source="admin_grant",
        granted_by_id=admin.id,
        grant_reason=payload.grant_reason,
        expires_at=payload.expires_at,
    )
    db.add(e); db.commit(); db.refresh(e)
    audit_log(db, admin.id, "enrollment.granted",
              # NB: ``user_id`` collides with audit_log's own kwarg; use
              # ``target_user_id`` for the granted-to user in metadata.
              {"id": e.id, "target_user_id": target.id, "course_id": c.id,
               "reason": payload.grant_reason[:200]})
    return e


@router.delete("/enrollments/{enrollment_id}", status_code=204)
def revoke_enrollment(
    enrollment_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    e = db.query(Enrollment).filter(
        Enrollment.id == enrollment_id,
        Enrollment.tenant_id == get_current_tenant_id(),
    ).first()
    if not e:
        raise NotFoundError("Enrollment not found")
    if e.revoked_at is not None:
        return  # idempotent
    e.revoked_at = datetime.now(timezone.utc)
    db.commit()
    audit_log(db, admin.id, "enrollment.revoked", {"id": e.id})


# ============================================================ ANNOUNCEMENTS

@router.get("/courses/{course_id}/announcements", response_model=list[CourseAnnouncementOut])
def list_announcements(course_id: int, db: Session = Depends(get_db)):
    c = _course_scope(db).filter(Course.id == course_id).first()
    if not c:
        raise NotFoundError("Course not found")
    return (db.query(CourseAnnouncement)
              .filter(CourseAnnouncement.course_id == c.id,
                      CourseAnnouncement.tenant_id == get_current_tenant_id())
              .order_by(CourseAnnouncement.is_pinned.desc(),
                        CourseAnnouncement.posted_at.desc())
              .all())


@router.post("/courses/{course_id}/announcements",
             response_model=CourseAnnouncementOut, status_code=201)
def create_announcement(
    course_id: int,
    payload: CourseAnnouncementCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    c = _course_scope(db).filter(Course.id == course_id).first()
    if not c:
        raise NotFoundError("Course not found")
    a = CourseAnnouncement(
        tenant_id=get_current_tenant_id(),
        course_id=c.id,
        title=payload.title,
        body=payload.body,
        is_pinned=payload.is_pinned,
        posted_by=admin.id,
    )
    db.add(a); db.commit(); db.refresh(a)
    audit_log(db, admin.id, "announcement.posted",
              {"id": a.id, "course_id": c.id})
    return a


@router.delete("/announcements/{ann_id}", status_code=204)
def delete_announcement(
    ann_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    a = db.query(CourseAnnouncement).filter(
        CourseAnnouncement.id == ann_id,
        CourseAnnouncement.tenant_id == get_current_tenant_id(),
    ).first()
    if not a:
        raise NotFoundError("Announcement not found")
    db.delete(a); db.commit()
    audit_log(db, admin.id, "announcement.deleted", {"id": ann_id})


# ============================================================ CATEGORIES

@router.get("/course-categories", response_model=list[CourseCategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return (db.query(CourseCategory)
              .filter(CourseCategory.tenant_id == get_current_tenant_id())
              .order_by(CourseCategory.display_order, CourseCategory.id)
              .all())


@router.post("/course-categories", response_model=CourseCategoryOut, status_code=201)
def create_category(
    payload: CourseCategoryCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    exists = db.query(CourseCategory.id).filter(
        CourseCategory.tenant_id == get_current_tenant_id(),
        CourseCategory.slug == payload.slug,
    ).first()
    if exists:
        raise ConflictError(f"Category slug '{payload.slug}' already exists.")
    cat = CourseCategory(tenant_id=get_current_tenant_id(), **payload.model_dump())
    db.add(cat); db.commit(); db.refresh(cat)
    audit_log(db, admin.id, "course_category.created",
              {"id": cat.id, "slug": cat.slug})
    return cat


@router.patch("/course-categories/{cat_id}", response_model=CourseCategoryOut)
def update_category(
    cat_id: int,
    payload: CourseCategoryUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    cat = db.query(CourseCategory).filter(
        CourseCategory.id == cat_id,
        CourseCategory.tenant_id == get_current_tenant_id(),
    ).first()
    if not cat:
        raise NotFoundError("Category not found")
    updates = payload.model_dump(exclude_unset=True)
    if "slug" in updates and updates["slug"] != cat.slug:
        clash = db.query(CourseCategory.id).filter(
            CourseCategory.tenant_id == get_current_tenant_id(),
            CourseCategory.slug == updates["slug"],
            CourseCategory.id != cat.id,
        ).first()
        if clash:
            raise ConflictError(f"Category slug '{updates['slug']}' already exists.")
    for k, v in updates.items():
        setattr(cat, k, v)
    db.commit(); db.refresh(cat)
    audit_log(db, admin.id, "course_category.updated",
              {"id": cat.id, "changed": sorted(updates.keys())})
    return cat


@router.delete("/course-categories/{cat_id}", status_code=204)
def delete_category(
    cat_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    cat = db.query(CourseCategory).filter(
        CourseCategory.id == cat_id,
        CourseCategory.tenant_id == get_current_tenant_id(),
    ).first()
    if not cat:
        raise NotFoundError("Category not found")
    db.delete(cat); db.commit()
    audit_log(db, admin.id, "course_category.deleted", {"id": cat_id})


# ============================================================ COURSE→CATEGORY LINKS

@router.get("/courses/{course_id}/categories", response_model=list[CourseCategoryOut])
def list_course_categories(course_id: int, db: Session = Depends(get_db)):
    """Categories currently linked to this course — used by the course
    editor's chip-style multi-select to show which categories are
    already tagged."""
    c = _course_scope(db).filter(Course.id == course_id).first()
    if not c:
        raise NotFoundError("Course not found")
    rows = (db.query(CourseCategory)
              .join(CourseCategoryLink,
                    CourseCategoryLink.category_id == CourseCategory.id)
              .filter(CourseCategoryLink.course_id == c.id,
                      CourseCategory.tenant_id == get_current_tenant_id())
              .order_by(CourseCategory.display_order, CourseCategory.id)
              .all())
    return rows


@router.post("/courses/{course_id}/categories/{cat_id}", status_code=204)
def link_course_category(
    course_id: int,
    cat_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    c = _course_scope(db).filter(Course.id == course_id).first()
    if not c:
        raise NotFoundError("Course not found")
    cat = db.query(CourseCategory).filter(
        CourseCategory.id == cat_id,
        CourseCategory.tenant_id == get_current_tenant_id(),
    ).first()
    if not cat:
        raise NotFoundError("Category not found")
    exists = db.query(CourseCategoryLink.id).filter(
        CourseCategoryLink.course_id == c.id,
        CourseCategoryLink.category_id == cat.id,
    ).first()
    if exists:
        return  # idempotent
    db.add(CourseCategoryLink(
        tenant_id=get_current_tenant_id(),
        course_id=c.id, category_id=cat.id,
    ))
    db.commit()
    audit_log(db, admin.id, "course_category.linked",
              {"course_id": c.id, "category_id": cat.id})


@router.delete("/courses/{course_id}/categories/{cat_id}", status_code=204)
def unlink_course_category(
    course_id: int,
    cat_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    link = db.query(CourseCategoryLink).filter(
        CourseCategoryLink.course_id == course_id,
        CourseCategoryLink.category_id == cat_id,
        CourseCategoryLink.tenant_id == get_current_tenant_id(),
    ).first()
    if link:
        db.delete(link); db.commit()
        audit_log(db, admin.id, "course_category.unlinked",
                  {"course_id": course_id, "category_id": cat_id})


# ============================================================ QUIZZES

@router.put("/quizzes/{lesson_id}", response_model=QuizOut)
def upsert_quiz_config(
    lesson_id: int,
    payload: QuizConfigUpsertIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Idempotent config upsert. Create the quiz row if it doesn't
    exist yet, or update the existing one."""
    lsn = db.query(Lesson).filter(
        Lesson.id == lesson_id,
        Lesson.tenant_id == get_current_tenant_id(),
        Lesson.is_deleted.is_(False),
    ).first()
    if not lsn:
        raise NotFoundError("Lesson not found")
    if lsn.lesson_type != "quiz":
        raise ValidationError("Lesson is not of type 'quiz'.")
    quiz = db.query(LmsQuiz).filter(LmsQuiz.lesson_id == lsn.id).first()
    if quiz is None:
        quiz = LmsQuiz(
            tenant_id=get_current_tenant_id(),
            lesson_id=lsn.id,
            **payload.model_dump(),
        )
        db.add(quiz)
    else:
        for k, v in payload.model_dump().items():
            setattr(quiz, k, v)
    db.commit(); db.refresh(quiz)
    audit_log(db, admin.id, "quiz.upserted", {"id": quiz.id, "lesson_id": lsn.id})
    return quiz


@router.get("/quizzes/{lesson_id}", response_model=QuizOut)
def get_quiz_config(lesson_id: int, db: Session = Depends(get_db)):
    quiz = db.query(LmsQuiz).filter(
        LmsQuiz.lesson_id == lesson_id,
        LmsQuiz.tenant_id == get_current_tenant_id(),
    ).first()
    if not quiz:
        raise NotFoundError("Quiz not configured for this lesson")
    return quiz


@router.get("/quizzes/{lesson_id}/questions", response_model=list[QuizQuestionOut])
def list_quiz_questions(lesson_id: int, db: Session = Depends(get_db)):
    quiz = db.query(LmsQuiz).filter(
        LmsQuiz.lesson_id == lesson_id,
        LmsQuiz.tenant_id == get_current_tenant_id(),
    ).first()
    if not quiz:
        return []
    return (db.query(LmsQuizQuestion)
              .filter(LmsQuizQuestion.quiz_id == quiz.id)
              .order_by(LmsQuizQuestion.position, LmsQuizQuestion.id)
              .all())


@router.post("/quizzes/{lesson_id}/questions", response_model=QuizQuestionOut, status_code=201)
def add_quiz_question(
    lesson_id: int,
    payload: QuizQuestionCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    quiz = db.query(LmsQuiz).filter(
        LmsQuiz.lesson_id == lesson_id,
        LmsQuiz.tenant_id == get_current_tenant_id(),
    ).first()
    if not quiz:
        raise NotFoundError("Quiz not configured — POST /quizzes/{lesson_id} first.")
    q = LmsQuizQuestion(
        tenant_id=get_current_tenant_id(),
        quiz_id=quiz.id,
        **payload.model_dump(),
    )
    db.add(q); db.commit(); db.refresh(q)
    audit_log(db, admin.id, "quiz.question_added",
              {"id": q.id, "quiz_id": quiz.id})
    return q


@router.patch("/quiz-questions/{q_id}", response_model=QuizQuestionOut)
def update_quiz_question(
    q_id: int,
    payload: QuizQuestionUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    q = db.query(LmsQuizQuestion).filter(
        LmsQuizQuestion.id == q_id,
        LmsQuizQuestion.tenant_id == get_current_tenant_id(),
    ).first()
    if not q:
        raise NotFoundError("Question not found")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(q, k, v)
    db.commit(); db.refresh(q)
    audit_log(db, admin.id, "quiz.question_updated",
              {"id": q.id, "changed": sorted(updates.keys())})
    return q


@router.delete("/quiz-questions/{q_id}", status_code=204)
def delete_quiz_question(
    q_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    q = db.query(LmsQuizQuestion).filter(
        LmsQuizQuestion.id == q_id,
        LmsQuizQuestion.tenant_id == get_current_tenant_id(),
    ).first()
    if not q:
        raise NotFoundError("Question not found")
    db.delete(q); db.commit()
    audit_log(db, admin.id, "quiz.question_deleted", {"id": q_id})


@router.get("/quiz-questions/{q_id}/options", response_model=list[QuizOptionOut])
def list_quiz_options(
    q_id: int,
    db: Session = Depends(get_db),
):
    """Admin: list options for a single quiz question, in position order.
    The admin quiz builder uses this on load so existing options surface
    in the UI — without it the builder could only ADD options and never
    show ones already stored."""
    # Existence check first to disambiguate 404 (question) from empty list (no options yet).
    q = db.query(LmsQuizQuestion).filter(
        LmsQuizQuestion.id == q_id,
        LmsQuizQuestion.tenant_id == get_current_tenant_id(),
    ).first()
    if not q:
        raise NotFoundError("Question not found")
    return (db.query(LmsQuizQuestionOption).filter(
        LmsQuizQuestionOption.question_id == q.id,
        LmsQuizQuestionOption.tenant_id == get_current_tenant_id(),
    ).order_by(LmsQuizQuestionOption.position, LmsQuizQuestionOption.id).all())


@router.post("/quiz-questions/{q_id}/options", response_model=QuizOptionOut, status_code=201)
def add_quiz_option(
    q_id: int,
    payload: QuizOptionCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    q = db.query(LmsQuizQuestion).filter(
        LmsQuizQuestion.id == q_id,
        LmsQuizQuestion.tenant_id == get_current_tenant_id(),
    ).first()
    if not q:
        raise NotFoundError("Question not found")
    o = LmsQuizQuestionOption(
        tenant_id=get_current_tenant_id(),
        question_id=q.id,
        **payload.model_dump(),
    )
    db.add(o); db.commit(); db.refresh(o)
    audit_log(db, admin.id, "quiz.option_added",
              {"id": o.id, "question_id": q.id})
    return o


@router.patch("/quiz-options/{o_id}", response_model=QuizOptionOut)
def update_quiz_option(
    o_id: int,
    payload: QuizOptionUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    o = db.query(LmsQuizQuestionOption).filter(
        LmsQuizQuestionOption.id == o_id,
        LmsQuizQuestionOption.tenant_id == get_current_tenant_id(),
    ).first()
    if not o:
        raise NotFoundError("Option not found")
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(o, k, v)
    db.commit(); db.refresh(o)
    audit_log(db, admin.id, "quiz.option_updated",
              {"id": o.id, "changed": sorted(updates.keys())})
    return o


@router.delete("/quiz-options/{o_id}", status_code=204)
def delete_quiz_option(
    o_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    o = db.query(LmsQuizQuestionOption).filter(
        LmsQuizQuestionOption.id == o_id,
        LmsQuizQuestionOption.tenant_id == get_current_tenant_id(),
    ).first()
    if not o:
        raise NotFoundError("Option not found")
    db.delete(o); db.commit()
    audit_log(db, admin.id, "quiz.option_deleted", {"id": o_id})
