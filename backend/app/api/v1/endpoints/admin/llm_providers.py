"""LLM provider CRUD with encrypted API key handling."""
import time
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user, get_super_admin_user
from app.core.exceptions import NotFoundError, ConflictError, ValidationError
from app.core.audit import audit_log
from app.core.crypto import crypto
from app.core.settings_store import settings_store
from app.models.user import User
from app.models.llm_provider import LLMProviderConfig
from app.schemas.llm_provider import (
    LLMProviderCreate, LLMProviderUpdate, LLMProviderOut,
)
from app.services.assistant.llm_registry import LLMRegistry, _provider_classes

router = APIRouter()


@router.get("", response_model=list[LLMProviderOut])
def list_providers(db: Session = Depends(get_db)):
    rows = (db.query(LLMProviderConfig)
            .order_by(LLMProviderConfig.priority,
                      LLMProviderConfig.id).all())
    active_id = settings_store.get("llm.active_provider_id")
    return [LLMProviderOut.from_row(r, is_active=(r.id == active_id))
            for r in rows]


@router.post("", response_model=LLMProviderOut, status_code=201)
def create_provider(payload: LLMProviderCreate,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    if payload.provider_type not in _provider_classes():
        raise ValidationError(
            f"Unknown provider_type: {payload.provider_type}")
    if db.query(LLMProviderConfig).filter_by(name=payload.name).first():
        raise ConflictError(f"Name '{payload.name}' already in use.")
    if not crypto and payload.api_key:
        raise ValidationError(
            "ENCRYPTION_KEY not configured — cannot store API keys.")
    row = LLMProviderConfig(
        name=payload.name, provider_type=payload.provider_type,
        model=payload.model,
        api_key_encrypted=(crypto.encrypt(payload.api_key)
                           if payload.api_key and crypto else None),
        base_url=payload.base_url, config=payload.config or {},
        is_enabled=payload.is_enabled, priority=payload.priority,
        created_by=admin.id,
    )
    db.add(row); db.commit(); db.refresh(row)
    audit_log(db, admin.id, "llm.provider_created",
              {"id": row.id, "type": row.provider_type, "model": row.model})
    return LLMProviderOut.from_row(row)


@router.patch("/{provider_id}", response_model=LLMProviderOut)
def update_provider(provider_id: int, payload: LLMProviderUpdate,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user)):
    row = db.get(LLMProviderConfig, provider_id)
    if not row: raise NotFoundError()
    data = payload.model_dump(exclude_unset=True)
    if "api_key" in data:
        new_key = data.pop("api_key")
        if new_key:
            if not crypto:
                raise ValidationError("ENCRYPTION_KEY not configured.")
            row.api_key_encrypted = crypto.encrypt(new_key)
        else:
            row.api_key_encrypted = None
    for k, v in data.items():
        setattr(row, k, v)
    db.commit(); db.refresh(row)
    LLMRegistry.invalidate(provider_id)
    audit_log(db, admin.id, "llm.provider_updated",
              {"id": provider_id, "fields": list(data.keys())})
    active_id = settings_store.get("llm.active_provider_id")
    return LLMProviderOut.from_row(row, is_active=(row.id == active_id))


@router.post("/{provider_id}/activate", response_model=LLMProviderOut)
def activate_provider(provider_id: int,
                      db: Session = Depends(get_db),
                      admin: User = Depends(get_admin_user)):
    row = db.get(LLMProviderConfig, provider_id)
    if not row or not row.is_enabled:
        raise ValidationError("Provider not found or disabled.")
    settings_store.set("llm.active_provider_id", provider_id,
                       db=db, updated_by=admin.id)
    LLMRegistry.invalidate(provider_id)
    audit_log(db, admin.id, "llm.provider_activated", {"id": provider_id})
    return LLMProviderOut.from_row(row, is_active=True)


@router.post("/{provider_id}/test")
def test_provider(provider_id: int,
                  admin: User = Depends(get_admin_user)):
    t0 = time.perf_counter()
    try:
        provider = LLMRegistry.get_by_id(provider_id)
        reply = provider.complete(
            system="You are a connectivity test responder. Reply 'pong'.",
            messages=[{"role": "user", "content": "ping"}],
        )
        return {"ok": True,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "preview": (reply or "")[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.delete("/{provider_id}", status_code=204)
def delete_provider(provider_id: int,
                    db: Session = Depends(get_db),
                    admin: User = Depends(get_super_admin_user)):
    row = db.get(LLMProviderConfig, provider_id)
    if not row: raise NotFoundError()
    if settings_store.get("llm.active_provider_id") == provider_id:
        raise ConflictError("Cannot delete the active provider — switch first.")
    db.delete(row); db.commit()
    LLMRegistry.invalidate(provider_id)
    audit_log(db, admin.id, "llm.provider_deleted", {"id": provider_id})
