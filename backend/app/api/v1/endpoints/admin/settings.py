"""Runtime settings — whitelisted keys with per-key validators.

Allow-list discipline (don't loosen this):
  Anything that drives behaviour at runtime gets a row here. The
  validator is what an admin actually CAN type. The /settings GET
  returns everything in DB; PATCH only accepts keys listed below.

Adding a new setting is a three-step ritual:
  1. Add the row to backend/seeds/default_settings.json (sets the
     default for fresh installs and future deploys — existing rows
     are NOT overwritten on re-seed).
  2. Add the key + a validator to EDITABLE here.
  3. Add the key to test_settings_editable.py's expected set so the
     drift guard stays honest.

If a setting is reachable via a dedicated endpoint (e.g.
payment.active_provider_id is also set via /admin/payment-providers/
{id}/activate), keep it in EDITABLE here too — admins should be able
to set it directly through Runtime Settings.
"""
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


# ----------------------------------------------------------- validators
def _short_str(max_len: int = 500):
    """Required non-empty string."""
    return lambda v: isinstance(v, str) and 1 <= len(v) <= max_len


def _optional_str(max_len: int = 500):
    """Empty string allowed (renders as 'hide this field' in UI), else
    string up to max_len."""
    return lambda v: isinstance(v, str) and len(v) <= max_len


def _optional_url(max_len: int = 500):
    """Empty string OR an http(s) URL. Defensive but not strict — a
    bad URL won't crash the page, it'll just look broken in the footer.
    Admins can always re-edit."""
    def ok(v):
        if not isinstance(v, str): return False
        if v == "": return True
        if len(v) > max_len: return False
        return v.startswith("http://") or v.startswith("https://")
    return ok


def _optional_email(max_len: int = 240):
    """Empty string OR something with an @ sign. Strict RFC-5322
    validation belongs at form-submit time on the client; this is a
    sanity gate."""
    def ok(v):
        if not isinstance(v, str): return False
        if v == "": return True
        if len(v) > max_len: return False
        return "@" in v and "." in v
    return ok


def _bool(v): return isinstance(v, bool)
def _int_in(lo: int, hi: int):
    return lambda v: isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _float_in(lo: float, hi: float):
    return lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


EDITABLE: dict[str, Callable] = {
    # AI chat operational limits
    "chat.daily_limit.anonymous":        _int_in(0, 1000),
    "chat.daily_limit.authenticated":    _int_in(0, 10000),
    "chat.max_input_chars":              _int_in(100, 32000),
    "chat.max_output_chars":             _int_in(100, 32000),
    "chat.tokens_per_day_authenticated": lambda v: isinstance(v, int) and v >= 0,
    "chat.cooldown_seconds":             lambda v: isinstance(v, (int, float)) and v >= 0,
    # Auth lockout policy
    "auth.lockout_threshold":            _int_in(1, 50),
    "auth.lockout_minutes":              _int_in(1, 1440),
    # LLM / payment provider plumbing
    "llm.active_provider_id":            lambda v: v is None or isinstance(v, int),
    "llm.fallback_provider_id":          lambda v: v is None or isinstance(v, int),
    "llm.cache_ttl_seconds":             lambda v: isinstance(v, int) and v >= 1,
    "payment.active_provider_id":        lambda v: v is None or isinstance(v, int),
    "payment.cache_ttl_seconds":         lambda v: isinstance(v, int) and v >= 1,
    # RAG / embeddings
    "embeddings.provider_id":            lambda v: v is None or isinstance(v, int),
    "embeddings.cache_ttl_seconds":      lambda v: isinstance(v, int) and v >= 1,
    "rag.top_k":                         _int_in(1, 20),
    "rag.min_similarity":                _float_in(0.0, 1.0),
    # PMI link-out URLs (chat surfaces these when intent matches)
    "pmi.course_bundle_url":             _optional_url(500),
    "pmi.eco_url":                       _optional_url(500),
    # AI assistant guardrails — folded into every LLM-bound handler's
    # system prompt at request time. Empty values = silent (skipped).
    "assistant.system_prompt_preamble":  _optional_str(2000),
    "assistant.allowed_topics":          _optional_str(2000),
    "assistant.banned_topics":           _optional_str(2000),
    "assistant.allowed_exceptions":      _optional_str(2000),
    "assistant.no_provider_message":     _optional_str(2000),
    # Pricing knobs (phase 1 + 2)
    "pricing.stack_offer_with_discount": _bool,
    "pricing.gst_percent":               _int_in(0, 100),
    # Landing-page copy (admin-editable, no redeploy needed)
    "landing.lead_section_heading":      _short_str(200),
    "landing.lead_cta_text":             _short_str(80),
    "landing.lead_post_submit_route":    _short_str(200),
    "landing.premium_upsell_title":      _short_str(120),
    "landing.premium_upsell_body":       _short_str(500),
    # Site chrome (header + footer, admin-editable per the unified-chrome rollout)
    "site.brand_name":                   _short_str(80),
    "site.tagline":                      _optional_str(240),
    "site.support_email":                _optional_email(240),
    "site.linkedin_url":                 _optional_url(),
    "site.youtube_url":                  _optional_url(),
    "site.twitter_url":                  _optional_url(),
    "site.copyright_text":               _short_str(240),
    "site.show_pricing_link":            _bool,
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
