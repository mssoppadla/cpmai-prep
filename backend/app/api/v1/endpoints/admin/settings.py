"""Runtime settings — whitelisted keys with per-key validators."""
from typing import Callable
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_admin_user
from app.core.exceptions import ValidationError
from app.core.audit import audit_log
from app.core.settings_store import settings_store
from app.models.user import User
from app.schemas.settings import SettingOut, SettingUpdate

router = APIRouter()

EDITABLE: dict[str, Callable] = {
    "chat.daily_limit.anonymous":        lambda v: isinstance(v, int) and 0 <= v <= 1000,
    "chat.daily_limit.authenticated":    lambda v: isinstance(v, int) and 0 <= v <= 10000,
    "chat.max_input_chars":              lambda v: isinstance(v, int) and 100 <= v <= 32000,
    "chat.max_output_chars":             lambda v: isinstance(v, int) and 100 <= v <= 32000,
    "chat.tokens_per_day_authenticated": lambda v: isinstance(v, int) and v >= 0,
    "chat.cooldown_seconds":             lambda v: isinstance(v, (int, float)) and v >= 0,
    "auth.lockout_threshold":            lambda v: isinstance(v, int) and 1 <= v <= 50,
    "auth.lockout_minutes":              lambda v: isinstance(v, int) and 1 <= v <= 1440,
    "llm.active_provider_id":            lambda v: v is None or isinstance(v, int),
    "llm.fallback_provider_id":          lambda v: v is None or isinstance(v, int),
    "llm.cache_ttl_seconds":             lambda v: isinstance(v, int) and v >= 1,
}


@router.get("", response_model=list[SettingOut])
def list_settings(db: Session = Depends(get_db)):
    return settings_store.all(db)


@router.patch("/{key}", response_model=SettingOut)
def update_setting(key: str, payload: SettingUpdate,
                   db: Session = Depends(get_db),
                   admin: User = Depends(get_admin_user)):
    if key not in EDITABLE:
        raise ValidationError(f"Setting '{key}' is not editable via API.")
    if not EDITABLE[key](payload.value):
        raise ValidationError("Value failed validation for this setting.")
    settings_store.set(key, payload.value, db=db, updated_by=admin.id)
    audit_log(db, admin.id, "setting.updated",
              {"key": key, "value": payload.value})
    return SettingOut(key=key, value=payload.value)
