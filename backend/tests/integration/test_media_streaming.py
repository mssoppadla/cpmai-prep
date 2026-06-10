"""The /uploads handler is a hard wall around paid media.

Images are public; videos/PDFs/docs require a valid, path-bound,
expiring token. Range requests must return 206 so video seeking works.
"""
from __future__ import annotations

import pytest

from app.core.media_tokens import sign_media_token


@pytest.fixture
def upload_root(tmp_path, monkeypatch):
    """Point the /uploads handler at a sandbox dir with a couple of files.

    The route reads module-level globals in app.main, so we patch those
    (the file is captured at import time and won't pick up env changes).
    """
    from app.main import app as _app  # noqa: F401 — ensure module imported
    import app.main as main_mod

    # Plant an image (public) and a video (protected).
    (tmp_path / "1/2026/06").mkdir(parents=True, exist_ok=True)
    img = tmp_path / "1/2026/06/pic.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
    vid = tmp_path / "1/2026/06/lecture.mp4"
    vid.write_bytes(b"VIDEO-BYTES-0123456789")  # 22 bytes

    monkeypatch.setattr(main_mod, "_UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "_UPLOAD_ROOT_RESOLVED", tmp_path.resolve())
    return tmp_path


IMG = "/uploads/1/2026/06/pic.png"
VID_REL = "1/2026/06/lecture.mp4"
VID = f"/uploads/{VID_REL}"


def test_image_served_publicly_without_token(client, upload_root):
    r = client.get(IMG)
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"\x89PNG")


def test_protected_video_404_without_token(client, upload_root):
    r = client.get(VID)
    assert r.status_code == 404


def test_protected_video_404_with_invalid_token(client, upload_root):
    r = client.get(f"{VID}?token=garbage")
    assert r.status_code == 404


def test_protected_video_served_with_valid_token(client, upload_root):
    tok = sign_media_token(VID_REL, user_id=1)
    r = client.get(f"{VID}?token={tok}")
    assert r.status_code == 200, r.text
    assert r.headers.get("accept-ranges") == "bytes"
    assert r.content == b"VIDEO-BYTES-0123456789"


def test_range_request_returns_206(client, upload_root):
    tok = sign_media_token(VID_REL, user_id=1)
    r = client.get(f"{VID}?token={tok}", headers={"Range": "bytes=0-4"})
    assert r.status_code == 206, r.text
    assert r.headers["content-range"] == "bytes 0-4/22"
    assert r.content == b"VIDEO"


def test_token_for_one_path_cannot_fetch_another(client, upload_root):
    # Token minted for the image's path must not unlock the video.
    tok = sign_media_token("1/2026/06/pic.png", user_id=1)
    r = client.get(f"{VID}?token={tok}")
    assert r.status_code == 404


def test_missing_file_404(client, upload_root):
    tok = sign_media_token("1/2026/06/nope.mp4", user_id=1)
    r = client.get(f"/uploads/1/2026/06/nope.mp4?token={tok}")
    assert r.status_code == 404
