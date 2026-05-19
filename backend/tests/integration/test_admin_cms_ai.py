"""Integration tests for the admin CMS AI endpoints.

These cover the HTTP surface: RBAC, audit logging, request validation,
schema typing. The actual LLM call is patched out — we already covered
the AI service's parsing logic in ``tests/unit/test_cms_ai_blocks.py``.
"""
from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import desc

from app.models.audit_log import AuditLog
from tests.conftest import auth_header


_GP_PATH = "/api/v1/admin/cms-ai/generate-page"
_FB_PATH = "/api/v1/admin/cms-ai/fill-block"
_IB_PATH = "/api/v1/admin/cms-ai/improve-block"


def _last_audit(db, action: str) -> AuditLog | None:
    return (db.query(AuditLog)
            .filter(AuditLog.action == action)
            .order_by(desc(AuditLog.id))
            .first())


# ----------------------------------------------------- generate-page

def test_generate_page_returns_normalised_blocks(client, db, admin, default_tenant):
    fake_blocks = [
        {"id": "abc", "type": "heading", "content": "Hi", "props": {"level": 1}},
        {"id": "def", "type": "paragraph", "content": "Body"},
    ]
    with patch("app.services.cms.ai_blocks.generate_page",
               return_value=fake_blocks):
        r = client.post(_GP_PATH,
                        headers=auth_header(client, admin.email),
                        json={"prompt": "Write a study guide"})
    assert r.status_code == 200, r.text
    assert r.json()["blocks"] == fake_blocks


def test_generate_page_writes_audit_log(client, db, admin, default_tenant):
    with patch("app.services.cms.ai_blocks.generate_page",
               return_value=[{"type": "paragraph", "content": "x"}]):
        client.post(_GP_PATH,
                    headers=auth_header(client, admin.email),
                    json={"prompt": "Write something"})
    row = _last_audit(db, "cms_ai.generate_page")
    assert row is not None
    assert row.tenant_id == 1
    assert row.user_id == admin.id
    assert row.metadata_json["block_count"] == 1
    assert "Write something" in row.metadata_json["prompt_excerpt"]


def test_generate_page_truncates_long_prompt_in_audit(client, db, admin, default_tenant):
    long_prompt = "x" * 1000
    with patch("app.services.cms.ai_blocks.generate_page",
               return_value=[]):
        client.post(_GP_PATH,
                    headers=auth_header(client, admin.email),
                    json={"prompt": long_prompt})
    row = _last_audit(db, "cms_ai.generate_page")
    assert row is not None
    # Truncated to 200 chars + ellipsis
    assert len(row.metadata_json["prompt_excerpt"]) <= 210


def test_generate_page_validates_empty_prompt(client, db, admin, default_tenant):
    r = client.post(_GP_PATH,
                    headers=auth_header(client, admin.email),
                    json={"prompt": ""})
    assert r.status_code == 422


def test_generate_page_validates_prompt_too_long(client, db, admin, default_tenant):
    r = client.post(_GP_PATH,
                    headers=auth_header(client, admin.email),
                    json={"prompt": "x" * 3000})
    assert r.status_code == 422


# ----------------------------------------------------- fill-block

def test_fill_block_returns_text(client, db, admin, default_tenant):
    with patch("app.services.cms.ai_blocks.fill_block",
               return_value="Generated body."):
        r = client.post(_FB_PATH,
                        headers=auth_header(client, admin.email),
                        json={"block_type": "paragraph",
                              "context": "Under heading 'Why CPMAI'"})
    assert r.status_code == 200, r.text
    assert r.json() == {"text": "Generated body."}


def test_fill_block_validates_unknown_type(client, db, admin, default_tenant):
    r = client.post(_FB_PATH,
                    headers=auth_header(client, admin.email),
                    json={"block_type": "imageGallery", "context": ""})
    assert r.status_code == 422


def test_fill_block_writes_audit_log(client, db, admin, default_tenant):
    with patch("app.services.cms.ai_blocks.fill_block",
               return_value="Text content here"):
        client.post(_FB_PATH,
                    headers=auth_header(client, admin.email),
                    json={"block_type": "heading", "context": "ctx"})
    row = _last_audit(db, "cms_ai.fill_block")
    assert row is not None
    assert row.tenant_id == 1
    assert row.metadata_json["block_type"] == "heading"
    assert row.metadata_json["result_chars"] == len("Text content here")


# ----------------------------------------------------- improve-block

def test_improve_block_returns_rewritten(client, db, admin, default_tenant):
    with patch("app.services.cms.ai_blocks.improve_block",
               return_value="Polished version."):
        r = client.post(_IB_PATH,
                        headers=auth_header(client, admin.email),
                        json={"text": "Original text.", "tone": "friendlier"})
    assert r.status_code == 200, r.text
    assert r.json() == {"text": "Polished version."}


def test_improve_block_validates_unknown_tone(client, db, admin, default_tenant):
    r = client.post(_IB_PATH,
                    headers=auth_header(client, admin.email),
                    json={"text": "x", "tone": "snarky"})
    assert r.status_code == 422


def test_improve_block_validates_empty_text(client, db, admin, default_tenant):
    r = client.post(_IB_PATH,
                    headers=auth_header(client, admin.email),
                    json={"text": "", "tone": "shorter"})
    assert r.status_code == 422


def test_improve_block_writes_audit_log(client, db, admin, default_tenant):
    with patch("app.services.cms.ai_blocks.improve_block",
               return_value="Fixed."):
        client.post(_IB_PATH,
                    headers=auth_header(client, admin.email),
                    json={"text": "Original.", "tone": "grammar"})
    row = _last_audit(db, "cms_ai.improve_block")
    assert row is not None
    assert row.metadata_json["tone"] == "grammar"
    assert row.metadata_json["input_chars"] == len("Original.")
    assert row.metadata_json["result_chars"] == len("Fixed.")


# ----------------------------------------------------- RBAC

def test_anonymous_gets_401_on_all_endpoints(client, db, default_tenant):
    for path, body in [
        (_GP_PATH, {"prompt": "x"}),
        (_FB_PATH, {"block_type": "paragraph", "context": ""}),
        (_IB_PATH, {"text": "x", "tone": "shorter"}),
    ]:
        r = client.post(path, json=body)
        assert r.status_code == 401, (path, r.text)


def test_regular_user_gets_403_on_all_endpoints(client, db, user, default_tenant):
    headers = auth_header(client, user.email)
    for path, body in [
        (_GP_PATH, {"prompt": "x"}),
        (_FB_PATH, {"block_type": "paragraph", "context": ""}),
        (_IB_PATH, {"text": "x", "tone": "shorter"}),
    ]:
        r = client.post(path, headers=headers, json=body)
        assert r.status_code == 403, (path, r.text)


def test_super_admin_can_call_all_endpoints(client, db, super_admin, default_tenant):
    with patch("app.services.cms.ai_blocks.generate_page",
               return_value=[]), \
         patch("app.services.cms.ai_blocks.fill_block",
               return_value="x"), \
         patch("app.services.cms.ai_blocks.improve_block",
               return_value="x"):
        headers = auth_header(client, super_admin.email)
        assert client.post(_GP_PATH, headers=headers,
                           json={"prompt": "x"}).status_code == 200
        assert client.post(_FB_PATH, headers=headers,
                           json={"block_type": "paragraph",
                                 "context": ""}).status_code == 200
        assert client.post(_IB_PATH, headers=headers,
                           json={"text": "x", "tone": "shorter"}).status_code == 200
