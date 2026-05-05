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
    active_id = settings_store.get("payment.active_provider_id")
    return [PaymentProviderOut.from_row(r, is_active=(r.id == active_id))
            for r in rows]


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
    row = db.get(PaymentProviderConfig, provider_id)
    if not row or not row.is_enabled:
        raise ValidationError("Provider not found or disabled.")
    if not row.public_key or not row.api_secret_encrypted:
        raise ValidationError("Provider missing public_key or api_secret.")
    settings_store.set("payment.active_provider_id", provider_id,
                       db=db, updated_by=admin.id)
    PaymentRegistry.invalidate()
    audit_log(db, admin.id, "payment.provider_activated", {"id": provider_id})
    return PaymentProviderOut.from_row(row, is_active=True)


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


@router.delete("/{provider_id}", status_code=204)
def delete_provider(provider_id: int,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_super_admin_user)):
    row = db.get(PaymentProviderConfig, provider_id)
    if not row: raise NotFoundError()
    if settings_store.get("payment.active_provider_id") == provider_id:
        raise ConflictError("Cannot delete the active provider — switch first.")
    db.delete(row); db.commit()
    PaymentRegistry.invalidate()
    audit_log(db, admin.id, "payment.provider_deleted", {"id": provider_id})
