"""Signed-media boundary + dashboard progress.

Pins that the LMS public API never leaks a raw paid-media path: enrolled
users get ``/uploads/...?token=`` URLs, external (YouTube) URLs pass
through untouched, and the dashboard enrollment payload carries a
computed progress percentage.
"""
from __future__ import annotations

import pytest

from app.core.media_tokens import verify_media_token
from app.models.lms import Chapter, Course, Enrollment, Lesson, LessonFile
from tests.conftest import auth_header


PUB = "/api/v1/lms"


@pytest.fixture
def course(db, default_tenant):
    c = Course(slug="ml-101", title="ML 101", is_published=True,
               completion_threshold_percent=100)
    db.add(c); db.commit(); db.refresh(c)
    return c


@pytest.fixture
def chapter(db, course):
    ch = Chapter(course_id=course.id, title="Module 1", position=10,
                 is_published=True)
    db.add(ch); db.commit(); db.refresh(ch)
    return ch


@pytest.fixture
def video_lesson(db, chapter):
    l = Lesson(chapter_id=chapter.id, lesson_type="video", title="Intro",
               position=10, is_published=True, is_mandatory=True,
               video_url="/uploads/1/2026/06/abc-intro.mp4",
               video_provider="r2")
    db.add(l); db.commit(); db.refresh(l)
    return l


@pytest.fixture
def enrollment(db, user, course):
    e = Enrollment(user_id=user.id, course_id=course.id, source="admin_grant")
    db.add(e); db.commit(); db.refresh(e)
    return e


def test_enrolled_video_url_is_signed(client, db, user, course, chapter,
                                      video_lesson, enrollment):
    r = client.get(f"{PUB}/courses/{course.slug}",
                   headers=auth_header(client, user.email))
    assert r.status_code == 200, r.text
    lsn = r.json()["chapters"][0]["lessons"][0]
    url = lsn["video_url"]
    assert url.startswith("/uploads/1/2026/06/abc-intro.mp4?token=")
    claims = verify_media_token(url.split("token=", 1)[1])
    assert claims is not None
    assert claims["path"] == "1/2026/06/abc-intro.mp4"
    assert claims["sub"] == str(user.id)


def test_enrolled_file_url_is_signed(client, db, user, course, chapter,
                                     video_lesson, enrollment):
    db.add(LessonFile(lesson_id=video_lesson.id, filename="notes.pdf",
                      file_url="/uploads/1/2026/06/abc-notes.pdf",
                      file_category="reference", position=1))
    db.commit()
    r = client.get(f"{PUB}/courses/{course.slug}",
                   headers=auth_header(client, user.email))
    files = r.json()["chapters"][0]["lessons"][0]["files"]
    assert len(files) == 1
    assert files[0]["file_url"].startswith(
        "/uploads/1/2026/06/abc-notes.pdf?token=")


def test_external_video_url_passthrough(client, db, user, course, chapter,
                                        enrollment):
    yt = Lesson(chapter_id=chapter.id, lesson_type="video", title="YT",
                position=20, is_published=True,
                video_url="https://youtu.be/abc123", video_provider="youtube")
    db.add(yt); db.commit()
    r = client.get(f"{PUB}/courses/{course.slug}",
                   headers=auth_header(client, user.email))
    lessons = r.json()["chapters"][0]["lessons"]
    yt_out = next(l for l in lessons if l["title"] == "YT")
    assert yt_out["video_url"] == "https://youtu.be/abc123"


def test_anon_gets_no_video_url(client, db, course, chapter, video_lesson):
    # Not free-preview, not enrolled → video nulled, never signed.
    r = client.get(f"{PUB}/courses/{course.slug}")
    lsn = r.json()["chapters"][0]["lessons"][0]
    assert lsn["video_url"] is None


def test_my_enrollments_includes_progress(client, db, user, course, chapter,
                                          video_lesson, enrollment):
    # Mark the single mandatory/published lesson complete → 100%.
    client.put(
        f"{PUB}/enrollments/{enrollment.id}/progress/{video_lesson.id}",
        headers=auth_header(client, user.email),
        json={"mark_completed": True},
    )
    r = client.get(f"{PUB}/me/enrollments",
                   headers=auth_header(client, user.email))
    assert r.status_code == 200, r.text
    row = next(e for e in r.json() if e["course_id"] == course.id)
    assert row["course_title"] == "ML 101"
    assert row["course_slug"] == "ml-101"
    assert row["lessons_total"] == 1
    assert row["lessons_completed"] == 1
    assert row["progress_percent"] == 100


def test_my_enrollments_zero_progress_when_nothing_done(
    client, db, user, course, chapter, video_lesson, enrollment,
):
    r = client.get(f"{PUB}/me/enrollments",
                   headers=auth_header(client, user.email))
    row = next(e for e in r.json() if e["course_id"] == course.id)
    assert row["lessons_total"] == 1
    assert row["lessons_completed"] == 0
    assert row["progress_percent"] == 0


def test_podcast_pointer_save_and_read(
    client, db, user, course, chapter, video_lesson, enrollment,
):
    # Save the podcast resume pointer…
    r = client.put(
        f"{PUB}/enrollments/{enrollment.id}/podcast",
        headers=auth_header(client, user.email),
        json={"lesson_id": video_lesson.id, "position_seconds": 12},
    )
    assert r.status_code == 200, r.text
    assert r.json()["podcast_lesson_id"] == video_lesson.id
    assert r.json()["podcast_position_seconds"] == 12

    # …and it round-trips on the enrollments list (cross-device resume).
    me = client.get(f"{PUB}/me/enrollments",
                    headers=auth_header(client, user.email))
    row = next(e for e in me.json() if e["course_id"] == course.id)
    assert row["podcast_lesson_id"] == video_lesson.id
    assert row["podcast_position_seconds"] == 12


def test_catalog_exposes_free_preview_video(client, db, course, chapter, video_lesson):
    # Mark the uploaded video lesson as a free preview…
    video_lesson.is_free_preview = True
    db.commit()
    r = client.get(f"{PUB}/courses")
    assert r.status_code == 200, r.text
    row = next(c for c in r.json() if c["slug"] == course.slug)
    assert row["preview_lesson_id"] == video_lesson.id
    # …and the catalog hands back a signed, anonymous-playable preview URL.
    assert (row["preview_video_url"] or "").startswith(
        "/uploads/1/2026/06/abc-intro.mp4?token=")


def test_catalog_no_preview_when_lesson_not_free(client, db, course, chapter, video_lesson):
    # video_lesson defaults to is_free_preview=False → no preview on the card.
    r = client.get(f"{PUB}/courses")
    row = next(c for c in r.json() if c["slug"] == course.slug)
    assert row["preview_video_url"] is None
    assert row["preview_lesson_id"] is None


def test_podcast_pointer_rejects_other_users_enrollment(
    client, db, user, admin, course, chapter, video_lesson, enrollment,
):
    # admin is not the owner of `enrollment` → 404 (opaque)
    r = client.put(
        f"{PUB}/enrollments/{enrollment.id}/podcast",
        headers=auth_header(client, admin.email),
        json={"lesson_id": video_lesson.id, "position_seconds": 5},
    )
    assert r.status_code == 404
