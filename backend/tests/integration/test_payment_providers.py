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


# ===================================================== PayPal-specific tests

def test_paypal_activates_non_inr_without_webhook_id(client, admin):
    """Webhook_id used to hard-block activation. Operators don't always
    have a webhook registered yet when they're setting up — and PayPal's
    in-browser capture flow works without webhooks. Activation must
    succeed; webhook authentication just stays in 'reject everything'
    mode until the ID is configured."""
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=h, json={
        "name": "PayPal Sandbox", "provider_type": "paypal", "mode": "test",
        "public_key": "AcDeClient",
        "api_secret": "ECkDeSecret",
        # No config.webhook_id — explicitly the case we're testing.
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.post(f"/api/v1/admin/payment-providers/{pid}/activate-non-inr",
                    headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_non_inr_active"] is True


def test_paypal_activates_non_inr_with_webhook_id(client, admin):
    """Happy path — admin supplies webhook_id at create time; activation
    proceeds and the config persists for the webhook handler to read."""
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=h, json={
        "name": "PayPal Live", "provider_type": "paypal", "mode": "live",
        "public_key": "AcLiveClient", "api_secret": "ECkLive",
        "config": {"webhook_id": "WH-LIVE-123"},
    })
    pid = r.json()["id"]
    r = client.post(f"/api/v1/admin/payment-providers/{pid}/activate-non-inr",
                    headers=h)
    assert r.status_code == 200, r.text


# ===================================================== Razorpay webhook diagnostic

def test_test_webhook_signature_matches_returns_ok(client, admin):
    """Round-trip the diagnostic: paste a body + the signature our own
    HMAC would produce → endpoint says ok=true. Lets the admin verify
    their secret matches the gateway without needing real prod traffic."""
    import hmac, hashlib
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=h, json={
        "name": "RZP Diag", "provider_type": "razorpay", "mode": "test",
        "public_key": "rzp_test_diag", "api_secret": "k_secret_diag",
        "webhook_secret": "whsec_secret_for_test",
    })
    pid = r.json()["id"]
    body = '{"event":"payment.captured","entity":"event"}'
    sig = hmac.new(b"whsec_secret_for_test", body.encode(),
                   hashlib.sha256).hexdigest()
    r = client.post(
        f"/api/v1/admin/payment-providers/{pid}/test-webhook-signature",
        headers=h, json={"payload": body, "signature": sig})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["secret_configured"] is True


def test_test_webhook_signature_mismatch_returns_actionable_reason(
        client, admin):
    """When the signature doesn't match (the common operator situation
    where they've rotated the secret on the gateway dashboard but not
    here), we must tell them WHY and HOW to fix it — not just 'false'."""
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=h, json={
        "name": "RZP MM", "provider_type": "razorpay", "mode": "test",
        "public_key": "rzp_test_mm", "api_secret": "k_secret",
        "webhook_secret": "whsec_correct",
    })
    pid = r.json()["id"]
    r = client.post(
        f"/api/v1/admin/payment-providers/{pid}/test-webhook-signature",
        headers=h, json={"payload": '{"x":1}',
                          "signature": "deadbeef" * 8})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["secret_configured"] is True
    # The reason must mention rotating / re-copying the secret so the
    # admin has a clear next action. Pin both alternatives so the
    # wording can evolve without the test going stale on minor edits.
    assert ("re-copy" in body["reason"]
            or "regenerate" in body["reason"])


def test_test_webhook_signature_no_secret_configured(client, admin):
    """If the provider row has no webhook_secret saved at all, the
    diagnostic must say so explicitly — otherwise the admin will copy
    secrets back and forth wondering why nothing matches."""
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=h, json={
        "name": "RZP NoSecret", "provider_type": "razorpay", "mode": "test",
        "public_key": "rzp_test_ns", "api_secret": "k_secret",
        # No webhook_secret.
    })
    pid = r.json()["id"]
    r = client.post(
        f"/api/v1/admin/payment-providers/{pid}/test-webhook-signature",
        headers=h, json={"payload": '{"x":1}', "signature": "aaaa"})
    body = r.json()
    assert body["ok"] is False
    assert body["secret_configured"] is False
    assert "no webhook secret" in body["reason"].lower()
