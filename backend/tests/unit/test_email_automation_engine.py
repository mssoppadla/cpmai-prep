"""Unit tests for the lifecycle email engine's pure logic.

Covers (contract §10.1): dedup-key builder per send policy, condition
evaluation semantics (incl. unknown-type fail-closed), attachment path
resolution (traversal guard, missing file, size cap) and the save-time
size check.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.models.email_automation import EmailAutomation
from app.models.subscription import Subscription
from app.models.user import User, UserRole
from app.services.email.attachments import (
    MAX_TOTAL_BYTES, resolve_attachment_paths, total_size_ok,
)
from app.services.email.automation import (
    build_dedup_key, evaluate_conditions,
)


def _auto(policy: str, id_: int = 7) -> EmailAutomation:
    a = EmailAutomation(name="t", trigger_key="user.signup",
                        subject="s", html_body="<p>b</p>",
                        send_policy=policy)
    a.id = id_
    return a


# ------------------------------------------------------------- dedup keys
def test_dedup_once_per_user_is_stable():
    a = _auto("once_per_user")
    assert build_dedup_key(a, 42, "evt1") == "7:42:once"
    assert build_dedup_key(a, 42, "evt2") == "7:42:once"  # ref ignored


def test_dedup_replace_pending_single_slot():
    a = _auto("replace_pending")
    assert build_dedup_key(a, 42, "evt1") == "7:42:latest"


def test_dedup_every_event_uses_ref():
    a = _auto("every_event")
    assert build_dedup_key(a, 42, "pay9") == "7:42:pay9"
    # No natural ref → ULID fallback, unique per call.
    k1, k2 = build_dedup_key(a, 42, None), build_dedup_key(a, 42, None)
    assert k1 != k2


# ------------------------------------------------------------- conditions
@pytest.fixture
def cond_user(db):
    u = User(email="cond@example.com", password_hash="x", name="Cond",
             role=UserRole.USER)
    db.add(u); db.commit(); db.refresh(u)
    return u


def test_unpaid_condition_matches_unpaid_user(db, cond_user):
    ok, _ = evaluate_conditions(
        db, cond_user, [{"type": "has_active_subscription", "value": False}])
    assert ok


def test_unpaid_condition_rejects_paid_user(db, cond_user):
    db.add(Subscription(
        user_id=cond_user.id, plan="pro", status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
    db.commit()
    ok, reason = evaluate_conditions(
        db, cond_user, [{"type": "has_active_subscription", "value": False}])
    assert not ok and "condition not met" in reason


def test_expired_subscription_counts_as_unpaid(db, cond_user):
    db.add(Subscription(
        user_id=cond_user.id, plan="pro", status="active",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
    db.commit()
    ok, _ = evaluate_conditions(
        db, cond_user, [{"type": "has_active_subscription", "value": False}])
    assert ok


def test_revoked_subscription_counts_as_unpaid(db, cond_user):
    db.add(Subscription(
        user_id=cond_user.id, plan="pro", status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        revoked_at=datetime.now(timezone.utc)))
    db.commit()
    ok, _ = evaluate_conditions(
        db, cond_user, [{"type": "has_active_subscription", "value": False}])
    assert ok


def test_signup_method_condition(db, cond_user):
    ok, _ = evaluate_conditions(
        db, cond_user, [{"type": "signup_method", "value": "password"}])
    assert ok
    ok, _ = evaluate_conditions(
        db, cond_user, [{"type": "signup_method", "value": "google"}])
    assert not ok


def test_days_since_signup(db, cond_user):
    # created_at just now → "more than 5 days ago" fails, "less than" holds.
    ok, _ = evaluate_conditions(
        db, cond_user, [{"type": "days_since_signup", "op": "gt", "days": 5}])
    assert not ok
    ok, _ = evaluate_conditions(
        db, cond_user, [{"type": "days_since_signup", "op": "lt", "days": 5}])
    assert ok


def test_unknown_condition_type_fails_closed(db, cond_user):
    ok, reason = evaluate_conditions(
        db, cond_user, [{"type": "totally_new_thing"}])
    assert not ok and "unknown condition type" in reason


def test_empty_conditions_always_match(db, cond_user):
    assert evaluate_conditions(db, cond_user, []) == (True, "")
    assert evaluate_conditions(db, cond_user, None) == (True, "")


def test_conditions_are_anded(db, cond_user):
    conds = [
        {"type": "signup_method", "value": "password"},        # holds
        {"type": "has_active_subscription", "value": True},    # fails
    ]
    ok, _ = evaluate_conditions(db, cond_user, conds)
    assert not ok


# ------------------------------------------------------------ attachments
@pytest.fixture
def upload_root(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_ROOT", str(tmp_path))
    return tmp_path


def _entry(url, filename="doc.pdf", size=100):
    return {"url": url, "filename": filename,
            "mime_type": "application/pdf", "size_bytes": size}


def test_resolve_valid_attachment(upload_root):
    d = upload_root / "1" / "2026" / "07"
    d.mkdir(parents=True)
    (d / "abc-doc.pdf").write_bytes(b"%PDF fake")
    resolved, err = resolve_attachment_paths(
        [_entry("/uploads/1/2026/07/abc-doc.pdf")])
    assert err is None
    assert len(resolved) == 1
    assert resolved[0]["filename"] == "doc.pdf"
    assert os.path.isfile(resolved[0]["path"])


def test_resolve_rejects_traversal(upload_root):
    (upload_root.parent / "secret.txt").write_text("nope")
    resolved, err = resolve_attachment_paths(
        [_entry("/uploads/../secret.txt")])
    assert resolved == [] and err is not None


def test_resolve_rejects_non_upload_url(upload_root):
    resolved, err = resolve_attachment_paths(
        [_entry("https://evil.example.com/x.pdf")])
    assert resolved == [] and "not an /uploads/ URL" in err


def test_resolve_reports_missing_file(upload_root):
    resolved, err = resolve_attachment_paths(
        [_entry("/uploads/1/2026/07/gone.pdf", filename="gone.pdf")])
    assert resolved == [] and "missing" in err


def test_resolve_enforces_total_size_cap(upload_root):
    d = upload_root / "1"
    d.mkdir()
    big = d / "big.pdf"
    big.write_bytes(b"x" * (MAX_TOTAL_BYTES + 1))
    resolved, err = resolve_attachment_paths([_entry("/uploads/1/big.pdf")])
    assert resolved == [] and "15MB" in err


def test_total_size_ok_save_time_check():
    assert total_size_ok([_entry("/uploads/a", size=MAX_TOTAL_BYTES)])
    assert not total_size_ok([
        _entry("/uploads/a", size=MAX_TOTAL_BYTES),
        _entry("/uploads/b", size=1),
    ])
    assert total_size_ok([])
    assert total_size_ok(None)
