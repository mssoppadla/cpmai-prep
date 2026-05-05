"""Razorpay runtime config: admins can add/activate/rotate without redeploying."""
from tests.conftest import auth_header


def test_admin_can_create_payment_provider(client, admin):
    headers = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=headers, json={
        "name": "Razorpay Test", "provider_type": "razorpay", "mode": "test",
        "public_key": "rzp_test_xxxxxxxxxxxx",
        "api_secret": "secret_yyyyyyyyyyyy",
        "webhook_secret": "whsec_zzzzzzzz",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    # Secret never returned — only a boolean flag
    assert "api_secret" not in body
    assert body["has_api_secret"] is True
    assert body["has_webhook_secret"] is True
    # Public key IS returned (it's not secret)
    assert body["public_key"] == "rzp_test_xxxxxxxxxxxx"


def test_secret_is_encrypted_at_rest(client, admin, db):
    headers = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=headers, json={
        "name": "Enc Test", "provider_type": "razorpay", "mode": "test",
        "public_key": "rzp_test_aa", "api_secret": "plain-secret-value",
    })
    pid = r.json()["id"]
    from app.models.payment_provider import PaymentProviderConfig
    row = db.get(PaymentProviderConfig, pid)
    # Stored bytes must NOT contain the plaintext
    assert b"plain-secret-value" not in (row.api_secret_encrypted or b"")
    # And must round-trip through the crypto service
    from app.core.crypto import crypto
    assert crypto.decrypt(row.api_secret_encrypted) == "plain-secret-value"


def test_activation_updates_runtime_active_provider(client, admin):
    headers = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=headers, json={
        "name": "Activate-Me", "provider_type": "razorpay", "mode": "test",
        "public_key": "rzp_test_bb", "api_secret": "s",
    })
    pid = r.json()["id"]
    r = client.post(f"/api/v1/admin/payment-providers/{pid}/activate",
                    headers=headers)
    assert r.status_code == 200
    assert r.json()["is_active"] is True
    # Verify via settings list
    r = client.get("/api/v1/admin/settings", headers=headers)
    active = next((s for s in r.json()
                   if s["key"] == "payment.active_provider_id"), None)
    assert active and active["value"] == pid


def test_cannot_delete_active_provider(client, admin, super_admin):
    headers = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=headers, json={
        "name": "Active-Del", "provider_type": "razorpay", "mode": "test",
        "public_key": "rzp_test_cc", "api_secret": "s",
    })
    pid = r.json()["id"]
    client.post(f"/api/v1/admin/payment-providers/{pid}/activate",
                headers=headers)
    super_headers = auth_header(client, super_admin.email)
    r = client.delete(f"/api/v1/admin/payment-providers/{pid}",
                      headers=super_headers)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_rotate_secret_replaces_ciphertext(client, admin, db):
    headers = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=headers, json={
        "name": "Rotate-Me", "provider_type": "razorpay", "mode": "test",
        "public_key": "rzp_test_dd", "api_secret": "old-secret",
    })
    pid = r.json()["id"]
    from app.models.payment_provider import PaymentProviderConfig
    old_ct = db.get(PaymentProviderConfig, pid).api_secret_encrypted
    r = client.patch(f"/api/v1/admin/payment-providers/{pid}",
                     headers=headers, json={"api_secret": "new-secret"})
    assert r.status_code == 200
    db.expire_all()
    new_ct = db.get(PaymentProviderConfig, pid).api_secret_encrypted
    assert new_ct != old_ct
    from app.core.crypto import crypto
    assert crypto.decrypt(new_ct) == "new-secret"
