"""Admin CRUD for payment provider configs.

Same shape as admin/llm_providers — encrypted secrets, hot-swap, smoke test.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user, get_super_admin_user
from app.core.exceptions import NotFoundError, ConflictError, ValidationError, AppError
from app.core.audit import audit_log
from app.core.crypto import crypto
from app.core.settings_store import settings_store
from app.models.user import User
from app.models.payment_provider import PaymentProviderConfig
from app.schemas.payment_provider import (
    PaymentProviderCreate, PaymentProviderUpdate, PaymentProviderOut,
)
from app.services.payment_registry import PaymentRegistry, PROVIDER_CLASSES

router = APIRouter()


@router.get("", response_model=list[PaymentProviderOut])
def list_providers(db: Session = Depends(get_db)):
    rows = (db.query(PaymentProviderConfig)
            .order_by(PaymentProviderConfig.priority,
                      PaymentProviderConfig.id).all())
    active_id     = settings_store.get("payment.active_provider_id")
    non_inr_id    = settings_store.get("payment.non_inr_provider_id")
    return [
        PaymentProviderOut.from_row(
            r,
            is_active=(r.id == active_id),
            is_non_inr_active=(r.id == non_inr_id),
        )
        for r in rows
    ]


@router.post("", response_model=PaymentProviderOut, status_code=201)
def create_provider(payload: PaymentProviderCreate,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    if payload.provider_type not in PROVIDER_CLASSES:
        raise ValidationError(f"Unknown provider_type: {payload.provider_type}")
    if db.query(PaymentProviderConfig).filter_by(name=payload.name).first():
        raise ConflictError(f"Name '{payload.name}' already in use.")
    if not crypto:
        raise ValidationError("ENCRYPTION_KEY not configured.")

    row = PaymentProviderConfig(
        name=payload.name,
        provider_type=payload.provider_type,
        mode=payload.mode,
        display_name=payload.display_name,
        public_key=payload.public_key,
        api_secret_encrypted=crypto.encrypt(payload.api_secret),
        webhook_secret_encrypted=(crypto.encrypt(payload.webhook_secret)
                                  if payload.webhook_secret else None),
        config=payload.config or {},
        is_enabled=payload.is_enabled,
        priority=payload.priority,
        created_by=admin.id,
    )
    db.add(row); db.commit(); db.refresh(row)
    PaymentRegistry.invalidate()
    audit_log(db, admin.id, "payment.provider_created",
              {"id": row.id, "type": row.provider_type, "mode": row.mode})
    return PaymentProviderOut.from_row(row)


@router.patch("/{provider_id}", response_model=PaymentProviderOut)
def update_provider(provider_id: int, payload: PaymentProviderUpdate,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    row = db.get(PaymentProviderConfig, provider_id)
    if not row: raise NotFoundError()
    data = payload.model_dump(exclude_unset=True)

    if "api_secret" in data:
        s = data.pop("api_secret")
        if s:
            if not crypto: raise ValidationError("ENCRYPTION_KEY not configured.")
            row.api_secret_encrypted = crypto.encrypt(s)
    if "webhook_secret" in data:
        s = data.pop("webhook_secret")
        if s:
            if not crypto: raise ValidationError("ENCRYPTION_KEY not configured.")
            row.webhook_secret_encrypted = crypto.encrypt(s)
        else:
            row.webhook_secret_encrypted = None

    for k, v in data.items():
        setattr(row, k, v)
    db.commit(); db.refresh(row)
    PaymentRegistry.invalidate()
    audit_log(db, admin.id, "payment.provider_updated",
              {"id": provider_id, "fields": list(data.keys())})
    active_id = settings_store.get("payment.active_provider_id")
    return PaymentProviderOut.from_row(row, is_active=(row.id == active_id))


@router.post("/{provider_id}/activate", response_model=PaymentProviderOut)
def activate_provider(provider_id: int,
                      db: Session = Depends(get_db),
                      admin: User = Depends(get_admin_user)):
    """Set this provider as the INR-rail (active) provider.

    Backward-compatible with the original single-provider semantics —
    most callers expect this endpoint to flip THE active provider,
    which in the new world means the INR-rail one. For non-INR routing
    use /activate-non-inr below.
    """
    row = db.get(PaymentProviderConfig, provider_id)
    if not row or not row.is_enabled:
        raise ValidationError("Provider not found or disabled.")
    if not row.public_key or not row.api_secret_encrypted:
        raise ValidationError("Provider missing public_key or api_secret.")
    settings_store.set("payment.active_provider_id", provider_id,
                       db=db, updated_by=admin.id)
    PaymentRegistry.invalidate()
    audit_log(db, admin.id, "payment.provider_activated", {"id": provider_id})
    non_inr_id = settings_store.get("payment.non_inr_provider_id")
    return PaymentProviderOut.from_row(
        row, is_active=True,
        is_non_inr_active=(row.id == non_inr_id))


@router.post("/{provider_id}/activate-non-inr", response_model=PaymentProviderOut)
def activate_non_inr_provider(provider_id: int,
                              db: Session = Depends(get_db),
                              admin: User = Depends(get_admin_user)):
    """Set this provider as the NON-INR-rail provider.

    Called once during PayPal setup to point all non-INR currency
    routing at the new PayPal provider. Razorpay continues to handle
    INR via the active_provider_id setting set by /activate above.

    Body-less; the provider_id in the path is the new non-INR provider.
    Pass provider_id=0 to clear the routing (non-INR orders then 503
    until reconfigured — defensive against accidentally pointing at
    the wrong provider).
    """
    if provider_id == 0:
        settings_store.set("payment.non_inr_provider_id", None,
                           db=db, updated_by=admin.id)
        PaymentRegistry.invalidate()
        audit_log(db, admin.id, "payment.non_inr_provider_cleared", {})
        # Return a dummy row so the OpenAPI schema stays consistent;
        # the frontend treats response_model strictly.
        raise NotFoundError(
            "Non-INR routing cleared. Re-activate a provider to enable "
            "non-INR payments."
        )

    row = db.get(PaymentProviderConfig, provider_id)
    if not row or not row.is_enabled:
        raise ValidationError("Provider not found or disabled.")
    if not row.public_key or not row.api_secret_encrypted:
        raise ValidationError("Provider missing public_key or api_secret.")
    # PayPal-specific note: webhook_id is RECOMMENDED but not required.
    # If unset, /paypal/webhook rejects all inbound events as
    # unverified — that just means dropped-tab buyer flows don't
    # auto-activate via webhook. The primary in-browser capture path
    # (/payments/paypal/capture) still works for both sandbox testing
    # and live checkouts, so admins can spin up PayPal without first
    # registering a webhook in the PayPal Developer dashboard. We
    # surface a soft warning in the audit log so the admin sees in
    # /admin/audit-logs that they're running without webhook
    # verification and can fix it later.
    webhook_id_status = "configured"
    if row.provider_type == "paypal":
        wh = (row.config or {}).get("webhook_id")
        if not wh:
            webhook_id_status = "missing"
    settings_store.set("payment.non_inr_provider_id", provider_id,
                       db=db, updated_by=admin.id)
    PaymentRegistry.invalidate()
    audit_log(db, admin.id, "payment.non_inr_provider_activated",
              {"id": provider_id, "type": row.provider_type,
                "paypal_webhook_id_status": webhook_id_status})
    active_id = settings_store.get("payment.active_provider_id")
    return PaymentProviderOut.from_row(
        row, is_active=(row.id == active_id),
        is_non_inr_active=True)


@router.post("/{provider_id}/test")
def test_provider(provider_id: int, admin: User = Depends(get_admin_user)):
    """Smoke-test the provider against the actual gateway."""
    try:
        provider = PaymentRegistry.get_by_id(provider_id)
        return provider.smoke_test()
    except AppError as e:
        body = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        return {"ok": False, **body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/{provider_id}/test-webhook-signature")
def test_webhook_signature(provider_id: int,
                            payload: dict,
                            _admin: User = Depends(get_admin_user)):
    """Diagnose webhook-signature mismatches without prod-log access.

    Razorpay (and any other HMAC-signed gateway) auto-disables a webhook
    endpoint that consistently 400s on signature verification. Recovering
    from that is a back-and-forth — re-copy the secret from the
    dashboard, hope the next delivery succeeds, repeat. This endpoint
    closes the loop: paste a real delivery's body + signature header
    from the gateway's "Recent deliveries" view, and we tell you
    whether our currently-configured secret would accept it.

    Body shape:
        {
            "payload":   "<raw event body, exactly as gateway sent it>",
            "signature": "<x-razorpay-signature header value>"
        }

    Returns:
        {
            "ok":              true | false,
            "reason":          short human-readable reason,
            "secret_configured": bool,
        }

    Doesn't touch state — pure verifier round-trip. Safe to re-run.
    """
    raw_body  = payload.get("payload")
    signature = payload.get("signature")
    if not isinstance(raw_body, str) or not isinstance(signature, str):
        return {"ok": False, "reason": "payload + signature must both be strings",
                "secret_configured": False}

    try:
        provider = PaymentRegistry.get_by_id(provider_id)
    except AppError as e:
        return {"ok": False, "reason": str(e.detail),
                "secret_configured": False}

    secret_configured = bool(getattr(provider, "_webhook_secret", None))
    if not secret_configured:
        return {
            "ok": False,
            "reason": ("This provider has no webhook secret configured. "
                       "Open the row → Edit → fill in 'Webhook secret' → Save."),
            "secret_configured": False,
        }

    # provider.verify_webhook_signature wants raw bytes (matches the
    # /payments/webhook code path). UTF-8 encode the pasted body the
    # same way Razorpay sends it.
    try:
        ok = provider.verify_webhook_signature(
            raw_body.encode("utf-8"), signature)
    except Exception as e:
        return {"ok": False, "reason": f"verifier crashed: {e}",
                "secret_configured": True}

    if ok:
        return {
            "ok": True,
            "reason": "Signature matches — this exact delivery would activate.",
            "secret_configured": True,
        }
    return {
        "ok": False,
        "reason": ("Signature does NOT match. The webhook secret stored "
                   "here disagrees with the one the gateway used to sign "
                   "this delivery. Either (a) re-copy the secret from "
                   "the gateway dashboard into /admin/payment-providers, "
                   "or (b) regenerate the secret in the dashboard and "
                   "paste the new value here. Don't forget to Save."),
        "secret_configured": True,
    }


@router.delete("/{provider_id}", status_code=204)
def delete_provider(provider_id: int,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_super_admin_user)):
    row = db.get(PaymentProviderConfig, provider_id)
    if not row: raise NotFoundError()
    if settings_store.get("payment.active_provider_id") == provider_id:
        raise ConflictError("Cannot delete the active provider — switch first.")
    if settings_store.get("payment.non_inr_provider_id") == provider_id:
        raise ConflictError(
            "Cannot delete the non-INR provider — point routing elsewhere first."
        )
    db.delete(row); db.commit()
    PaymentRegistry.invalidate()
    audit_log(db, admin.id, "payment.provider_deleted", {"id": provider_id})
