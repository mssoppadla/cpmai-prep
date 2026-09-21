"""/admin/storage pins — the no-false-orphan guarantee + trash lifecycle.

The one bug this suite exists to prevent: a LINKED file being listed
(or worse, trashed) as unlinked. Everything else — held window, system
classification, action-time re-verification, restore semantics,
candidate keep/discard, byte-confirmed empty-trash — supports that.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from app.models.lms import Chapter, Course, Lesson, LessonFile
from app.models.media import MediaCandidate, MediaTrash
from tests.conftest import auth_header

OVERVIEW = "/api/v1/admin/storage/overview"
FILES = "/api/v1/admin/storage/files"
TRASH = "/api/v1/admin/storage/trash"
TRASH_ITEMS = "/api/v1/admin/storage/trash-items"
RESTORE = "/api/v1/admin/storage/restore"
EMPTY = "/api/v1/admin/storage/empty-trash"
CANDIDATES = "/api/v1/admin/storage/candidates"


@pytest.fixture
def upload_root(tmp_path, monkeypatch):
    """Point both storage modules at a throwaway uploads tree."""
    import app.api.v1.endpoints.admin.storage as storage_ep
    import app.services.storage_scan as scan_mod
    monkeypatch.setattr(storage_ep, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(scan_mod, "UPLOAD_ROOT", tmp_path)
    return tmp_path


def _mk_file(root: Path, rel: str, size: int = 1024,
             age_hours: float = 48.0) -> str:
    """Create a file under the fake uploads root; default mtime is past
    the 24h hold window. Returns its /uploads/... URL."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    ts = time.time() - age_hours * 3600
    os.utime(p, (ts, ts))
    return "/uploads/" + rel


@pytest.fixture
def course_tree(db, admin):
    c = Course(tenant_id=1, slug="storage-course", title="Storage Course",
               base_price_paise=0, currency="INR", enrollment_type="paid",
               is_published=True, created_by=admin.id)
    db.add(c); db.commit(); db.refresh(c)
    ch = Chapter(tenant_id=1, course_id=c.id, title="Live sessions", position=0)
    db.add(ch); db.commit(); db.refresh(ch)
    lsn = Lesson(tenant_id=1, chapter_id=ch.id, lesson_type="video",
                 title="Sept Batch Live Class", position=0)
    db.add(lsn); db.commit(); db.refresh(lsn)
    return c, ch, lsn


def _rows(client, admin, status="all", q=""):
    r = client.get(FILES, params={"status": status, "q": q},
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    return {row["path"]: row for row in r.json()}


# ------------------------------------------------- classification pins

def test_linked_file_never_lists_as_unlinked(client, db, admin,
                                             upload_root, course_tree):
    """THE pin. A file referenced anywhere must classify as linked, with
    the course → section → lesson context on the ref."""
    c, ch, lsn = course_tree
    video = _mk_file(upload_root, "1/2026/08/aaa-video.mp4", size=5000)
    lsn.video_url = video
    db.commit()

    rows = _rows(client, admin)
    assert rows[video]["status"] == "linked"
    ref = rows[video]["links"][0]
    assert ref["kind"] == "lesson_video"
    assert ref["course_title"] == c.title
    assert ref["section_title"] == ch.title
    assert ref["admin_href"] == f"/admin/lessons/{lsn.id}"
    assert rows[video] not in _rows(client, admin, status="unlinked").values()


def test_every_reference_location_counts_as_linked(client, db, admin,
                                                   upload_root, course_tree):
    """Body-block JSON, lesson files, course cover, announcement text —
    each keeps its file out of the unlinked pool."""
    from app.models.exam_set import ExamSet
    from app.models.lms import CourseAnnouncement
    from app.models.testimonial import Testimonial
    c, ch, lsn = course_tree
    body = _mk_file(upload_root, "1/2026/08/bbb-diagram.png")
    attach = _mk_file(upload_root, "1/2026/08/ccc-notes.pdf")
    cover = _mk_file(upload_root, "1/2026/08/ddd-cover.jpg")
    ann = _mk_file(upload_root, "1/2026/08/eee-handout.pdf")
    es_cover = _mk_file(upload_root, "1/2026/08/es-cover.jpg")
    photo = _mk_file(upload_root, "1/2026/08/tm-photo.png")

    lsn.body_blocks = [{"type": "image", "props": {"url": body}}]
    c.cover_image_url = cover
    db.add(LessonFile(tenant_id=1, lesson_id=lsn.id, filename="notes.pdf",
                      file_url=attach))
    db.add(CourseAnnouncement(tenant_id=1, course_id=c.id, title="Handout",
                              body=f"Download: {ann} today"))
    db.add(ExamSet(name="Storage ES", slug="storage-es",
                   cover_image_url=es_cover))
    db.add(Testimonial(name="Asha", quote="Great!", photo_url=photo))
    db.commit()

    rows = _rows(client, admin)
    for url, kind in [(body, "lesson_body"), (attach, "lesson_file"),
                      (cover, "course_cover"), (ann, "announcement"),
                      (es_cover, "exam_set_cover"),
                      (photo, "testimonial_photo")]:
        assert rows[url]["status"] == "linked", url
        assert any(r["kind"] == kind for r in rows[url]["links"]), url


def test_unlinked_held_and_system_classification(client, db, admin,
                                                 upload_root):
    orphan = _mk_file(upload_root, "1/2026/07/fff-old.mp4")
    fresh = _mk_file(upload_root, "1/2026/09/ggg-new.mp4", age_hours=1)
    invoice = _mk_file(upload_root, "invoices/INV-1.pdf")

    rows = _rows(client, admin)
    assert rows[orphan]["status"] == "unlinked"
    assert rows[fresh]["status"] == "held"
    assert rows[invoice]["status"] == "system"


# ------------------------------------------------- trash action safety

def test_trash_reverifies_and_skips_linked_held_system(
        client, db, admin, upload_root, course_tree):
    """Action-time re-verify: even when the CALLER claims a path is
    unlinked, a live link (created after their page loaded), a young
    file, or a system path is skipped — only the true orphan moves."""
    _, _, lsn = course_tree
    orphan = _mk_file(upload_root, "1/2026/07/o-orphan.mp4", size=2048)
    linked = _mk_file(upload_root, "1/2026/07/l-linked.mp4")
    fresh = _mk_file(upload_root, "1/2026/09/f-fresh.mp4", age_hours=1)
    invoice = _mk_file(upload_root, "invoices/INV-2.pdf")
    lsn.video_url = linked   # the race: linked after the listing
    db.commit()

    r = client.post(TRASH, json={"paths": [orphan, linked, fresh, invoice]},
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trashed"] == [orphan]
    reasons = {s["path"]: s["reason"] for s in body["skipped"]}
    assert reasons == {linked: "linked", fresh: "held", invoice: "system"}
    # linked skip carries the proof
    linked_skip = next(s for s in body["skipped"] if s["path"] == linked)
    assert linked_skip["links"][0]["kind"] == "lesson_video"
    # the orphan physically moved; the linked file did not
    assert not (upload_root / "1/2026/07/o-orphan.mp4").exists()
    assert (upload_root / "1/2026/07/l-linked.mp4").exists()
    assert db.query(MediaTrash).count() == 1


def test_restore_file_only_returns_to_original_path(client, db, admin,
                                                    upload_root):
    orphan = _mk_file(upload_root, "1/2026/07/r-back.mp4", size=777)
    r = client.post(TRASH, json={"paths": [orphan]},
                    headers=auth_header(client, admin.email))
    assert r.json()["trashed"] == [orphan]
    tid = client.get(TRASH_ITEMS,
                     headers=auth_header(client, admin.email)).json()[0]["id"]

    r = client.post(RESTORE, json={"trash_id": tid},
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    assert r.json()["restored_path"] == orphan
    assert (upload_root / "1/2026/07/r-back.mp4").exists()
    # back to unlinked in the listing, gone from trash
    assert _rows(client, admin)[orphan]["status"] == "unlinked"
    assert client.get(TRASH_ITEMS,
                      headers=auth_header(client, admin.email)).json() == []


def test_empty_trash_requires_exact_byte_confirm(client, db, admin,
                                                 upload_root):
    orphan = _mk_file(upload_root, "1/2026/07/e-bytes.mp4", size=4096)
    client.post(TRASH, json={"paths": [orphan]},
                headers=auth_header(client, admin.email))

    r = client.post(EMPTY, json={"confirm_bytes": 1},
                    headers=auth_header(client, admin.email))
    assert r.status_code == 409, r.text

    r = client.post(EMPTY, json={"confirm_bytes": 4096},
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 1, "freed_bytes": 4096}
    assert list((upload_root / ".trash").glob("*")) == []


# ------------------------------------------------- candidates

def _mk_candidate(client, db, admin, upload_root, lsn):
    parent = _mk_file(upload_root, "1/2026/08/p-parent.mp4", size=9000)
    cand = _mk_file(upload_root, "1/2026/09/c-cand.webm", size=3000)
    lsn.video_url = parent
    db.commit()
    r = client.post(CANDIDATES,
                    json={"parent_path": parent, "candidate_path": cand,
                          "lesson_id": lsn.id},
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    return parent, cand, r.json()["id"]


def test_candidate_files_never_deletable_while_pending(
        client, db, admin, upload_root, course_tree):
    _, _, lsn = course_tree
    parent, cand, _cid = _mk_candidate(client, db, admin, upload_root, lsn)
    rows = _rows(client, admin)
    assert rows[cand]["status"] == "candidate"
    assert rows[cand]["candidate"]["parent_path"] == parent
    assert rows[cand]["candidate"]["savings_pct"] == 67
    assert any(r["kind"] == "lesson_video"
               for r in rows[cand]["candidate"]["parent_links"])
    r = client.post(TRASH, json={"paths": [cand]},
                    headers=auth_header(client, admin.email))
    assert r.json()["trashed"] == []


def test_keep_candidate_switches_lesson_and_trashes_original(
        client, db, admin, upload_root, course_tree):
    _, _, lsn = course_tree
    parent, cand, cid = _mk_candidate(client, db, admin, upload_root, lsn)
    r = client.post(f"{CANDIDATES}/{cid}/decide", json={"action": "keep"},
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    db.refresh(lsn)
    assert lsn.video_url == cand
    items = client.get(TRASH_ITEMS,
                       headers=auth_header(client, admin.email)).json()
    assert items[0]["original_path"] == parent
    assert items[0]["is_kept_candidate_original"] is True
    assert items[0]["was_links"][0]["kind"] == "lesson_video"

    # Revert: restore with revert_lesson → lesson serves original again,
    # candidate returns to pending.
    r = client.post(RESTORE, json={"trash_id": items[0]["id"],
                                   "revert_lesson": True},
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    assert r.json()["reverted_lesson"] is True
    db.refresh(lsn)
    assert lsn.video_url == parent
    mc = db.query(MediaCandidate).filter_by(id=cid).one()
    assert mc.status == "pending"


def test_restore_revert_refuses_when_lesson_changed(
        client, db, admin, upload_root, course_tree):
    """Orphaned-target case: the lesson's video changed (or lesson is
    gone) after the switch → restore completes file-only with a notice,
    the lesson is not touched."""
    _, _, lsn = course_tree
    parent, cand, cid = _mk_candidate(client, db, admin, upload_root, lsn)
    client.post(f"{CANDIDATES}/{cid}/decide", json={"action": "keep"},
                headers=auth_header(client, admin.email))
    lsn.video_url = "/uploads/1/2026/09/zz-replacement.mp4"
    db.commit()
    tid = client.get(TRASH_ITEMS,
                     headers=auth_header(client, admin.email)).json()[0]["id"]
    r = client.post(RESTORE, json={"trash_id": tid, "revert_lesson": True},
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    assert r.json()["reverted_lesson"] is False
    assert r.json()["notice"]
    db.refresh(lsn)
    assert lsn.video_url == "/uploads/1/2026/09/zz-replacement.mp4"


def test_discard_candidate_deletes_file_keeps_lesson(
        client, db, admin, upload_root, course_tree):
    _, _, lsn = course_tree
    parent, cand, cid = _mk_candidate(client, db, admin, upload_root, lsn)
    r = client.post(f"{CANDIDATES}/{cid}/decide", json={"action": "discard"},
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200 and r.json()["status"] == "discarded"
    db.refresh(lsn)
    assert lsn.video_url == parent
    assert not (upload_root / "1/2026/09/c-cand.webm").exists()
    assert (upload_root / "1/2026/08/p-parent.mp4").exists()


# ------------------------------------------------- lesson-file delete → trash

def test_lesson_file_delete_moves_to_trash(client, db, admin, upload_root,
                                           course_tree):
    _, _, lsn = course_tree
    url = _mk_file(upload_root, "1/2026/08/hhh-worksheet.pdf", size=512)
    lf = LessonFile(tenant_id=1, lesson_id=lsn.id,
                    filename="worksheet.pdf", file_url=url)
    db.add(lf); db.commit(); db.refresh(lf)

    r = client.delete(f"/api/v1/admin/lesson-files/{lf.id}",
                      headers=auth_header(client, admin.email))
    assert r.status_code == 204, r.text
    assert not (upload_root / "1/2026/08/hhh-worksheet.pdf").exists()
    items = client.get(TRASH_ITEMS,
                       headers=auth_header(client, admin.email)).json()
    assert items[0]["original_path"] == url
    assert items[0]["was_links"][0]["kind"] == "lesson_file"


# ------------------------------------------------- overview

def test_overview_totals(client, db, admin, upload_root, course_tree):
    _, _, lsn = course_tree
    linked = _mk_file(upload_root, "1/2026/08/ov-linked.mp4", size=3000)
    _mk_file(upload_root, "1/2026/07/ov-orphan.mp4", size=1000)
    lsn.video_url = linked
    db.commit()
    r = client.get(OVERVIEW, headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["linked_bytes"] == 3000
    assert body["unlinked_bytes"] == 1000
    assert body["counts"]["linked"] == 1
    assert body["counts"]["unlinked"] == 1


# ------------------------------------------------- free-preview clip gate

def test_visitor_gets_only_preview_clip(client, db, admin, upload_root,
                                        course_tree):
    """Option 3: a free-preview lesson with a generated clip serves the
    CLIP to non-enrolled viewers — the full video URL must not appear
    anywhere in the public payload."""
    c, ch, lsn = course_tree
    lsn.video_url = "/uploads/1/2026/08/full-lecture.mp4"
    lsn.is_free_preview = True
    lsn.free_preview_seconds = 90
    lsn.preview_video_url = "/uploads/1/2026/09/preview-90s.webm"
    db.commit()

    r = client.get(f"/api/v1/lms/courses/{c.slug}")
    assert r.status_code == 200, r.text
    payload = json.dumps(r.json())
    assert "full-lecture.mp4" not in payload
    lessons = r.json()["chapters"][0]["lessons"]
    assert "preview-90s.webm" in (lessons[0]["video_url"] or "")
    assert lessons[0]["free_preview_seconds"] == 90


# ------------------------------------------------- shared files ("choose from library")

def test_shared_lesson_file_delete_keeps_bytes_while_other_lesson_uses_it(
        client, db, admin, upload_root, course_tree):
    """Two lessons attach the SAME upload (library picker → no copy).
    Detaching it from one lesson must not trash the file the other
    still serves; detaching the last reference does."""
    _, ch, lsn = course_tree
    other = Lesson(tenant_id=1, chapter_id=ch.id, lesson_type="text",
                   title="Other lesson", position=1)
    db.add(other); db.commit(); db.refresh(other)
    url = _mk_file(upload_root, "1/2026/09/shared-deck.pdf", size=512)
    a = LessonFile(tenant_id=1, lesson_id=lsn.id, filename="deck.pdf", file_url=url)
    b = LessonFile(tenant_id=1, lesson_id=other.id, filename="deck.pdf", file_url=url)
    db.add_all([a, b]); db.commit(); db.refresh(a); db.refresh(b)

    r = client.delete(f"/api/v1/admin/lesson-files/{a.id}",
                      headers=auth_header(client, admin.email))
    assert r.status_code == 204, r.text
    assert (upload_root / "1/2026/09/shared-deck.pdf").exists()
    assert client.get(TRASH_ITEMS, headers=auth_header(client, admin.email)).json() == []
    # still listed as linked to the other lesson
    assert _rows(client, admin)[url]["status"] == "linked"

    r = client.delete(f"/api/v1/admin/lesson-files/{b.id}",
                      headers=auth_header(client, admin.email))
    assert r.status_code == 204, r.text
    assert not (upload_root / "1/2026/09/shared-deck.pdf").exists()
    items = client.get(TRASH_ITEMS, headers=auth_header(client, admin.email)).json()
    assert [t["original_path"] for t in items] == [url]


def test_shared_video_delete_of_attachment_keeps_video(
        client, db, admin, upload_root, course_tree):
    """A file used as one lesson's VIDEO and another's attachment: removing
    the attachment row leaves the video intact."""
    _, ch, lsn = course_tree
    url = _mk_file(upload_root, "1/2026/09/lecture.mp4", size=4096)
    lsn.video_url = url; lsn.video_provider = "r2"
    other = Lesson(tenant_id=1, chapter_id=ch.id, lesson_type="text",
                   title="Notes", position=1)
    db.add(other); db.commit(); db.refresh(other)
    lf = LessonFile(tenant_id=1, lesson_id=other.id, filename="lecture.mp4", file_url=url)
    db.add(lf); db.commit(); db.refresh(lf)
    r = client.delete(f"/api/v1/admin/lesson-files/{lf.id}",
                      headers=auth_header(client, admin.email))
    assert r.status_code == 204, r.text
    assert (upload_root / "1/2026/09/lecture.mp4").exists()


def test_files_kind_filter(client, db, admin, upload_root):
    """The library picker asks for videos only."""
    v = _mk_file(upload_root, "1/2026/09/k-clip.mp4")
    p = _mk_file(upload_root, "1/2026/09/k-deck.pdf")
    i = _mk_file(upload_root, "1/2026/09/k-cover.png")
    def kinds(kind):
        r = client.get(FILES, params={"kind": kind},
                       headers=auth_header(client, admin.email))
        assert r.status_code == 200, r.text
        return {row["path"] for row in r.json()}
    assert kinds("video") == {v}
    assert kinds("image") == {i}
    assert kinds("document") == {p}
    assert {v, p, i} <= kinds("")
