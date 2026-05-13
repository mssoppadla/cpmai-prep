"""GDPR self-service: data export + account deletion.

Covers the new /users/me/export and DELETE /users/me endpoints. Asserts:
  • Export includes all user-scoped collections the spec calls out.
  • Delete soft-deletes the row (NOT a hard delete) and redacts PII.
  • Delete preserves financial rows (payments, subscriptions).
  • Post-delete, the issued token is rejected on the next request.
"""
from app.models.payment import Payment
from app.models.subscription import Subscription
from app.models.user import User
from tests.conftest import auth_header


def test_export_returns_user_scoped_collections(client, user, db):
    db.add(Subscription(
        user_id=user.id, plan="premium", status="active",
    ))
    db.add(Payment(
        user_id=user.id, amount_paise=99900, currency="INR",
        provider_order_id="order_test_1",
        idempotency_key="idem_test_1",
        status="captured",
    ))
    db.commit()

    h = auth_header(client, user.email)
    r = client.get("/api/v1/users/me/export", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()

    # Every collection the spec promises must exist as a key — empty
    # arrays are fine, missing keys break clients.
    for key in ("user", "exam_attempts", "subscriptions", "payments",
                "assistant_log", "leads", "generated_at"):
        assert key in body, f"export missing key: {key}"

    assert body["user"]["email"] == user.email
    assert body["user"]["id"] == user.id
    assert len(body["subscriptions"]) == 1
    assert body["subscriptions"][0]["plan"] == "premium"
    assert len(body["payments"]) == 1
    assert body["payments"][0]["amount_paise"] == 99900


def test_export_requires_auth(client):
    r = client.get("/api/v1/users/me/export")
    assert r.status_code == 401


def test_delete_redacts_pii_and_soft_deletes(client, user, db):
    user_id = user.id
    original_email = user.email
    h = auth_header(client, user.email)

    r = client.delete("/api/v1/users/me", headers=h)
    assert r.status_code == 204, r.text

    # Row still exists — soft delete only.
    db.expire_all()
    row = db.get(User, user_id)
    assert row is not None
    assert row.is_active is False
    assert row.deleted_at is not None
    assert row.email == f"deleted-{user_id}@redacted.invalid"
    assert row.email != original_email
    assert row.name is None
    assert row.password_hash is None
    assert row.google_id is None


def test_delete_preserves_financial_rows(client, user, db):
    db.add(Payment(
        user_id=user.id, amount_paise=99900, currency="INR",
        provider_order_id="order_keep_me",
        idempotency_key="idem_keep_me",
        status="captured",
    ))
    db.add(Subscription(user_id=user.id, plan="premium", status="active"))
    db.commit()

    h = auth_header(client, user.email)
    r = client.delete("/api/v1/users/me", headers=h)
    assert r.status_code == 204

    db.expire_all()
    # Financials retained — Indian tax law requires 7-year retention.
    assert db.query(Payment).filter_by(user_id=user.id).count() == 1
    assert db.query(Subscription).filter_by(user_id=user.id).count() == 1


def test_post_delete_token_is_rejected(client, user):
    h = auth_header(client, user.email)
    assert client.delete("/api/v1/users/me", headers=h).status_code == 204
    # is_active=False blocks the dependency in get_current_user.
    r = client.get("/api/v1/users/me", headers=h)
    assert r.status_code == 401
