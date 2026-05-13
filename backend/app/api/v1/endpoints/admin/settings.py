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


# Keys whose ``value`` should be masked in GET responses. The PATCH
# endpoint still accepts plaintext (no other way to update a secret).
# Source of truth for "is this key secret" lives in the geoip package
# for geoip-related keys; other secret-bearing modules add to this set
# alongside the keys themselves.
from app.services.geoip.settings import SECRET_KEYS as _GEOIP_SECRET_KEYS
SECRET_KEYS: frozenset[str] = frozenset(_GEOIP_SECRET_KEYS)


# Validator for ints stored as JSON-number or JSON-string. Settings
# table values come in as JSON, but admin inputs from a text field
# arrive as strings; we coerce defensively at the validator boundary.
def _int_str_in(lo: int, hi: int):
    def ok(v):
        if isinstance(v, bool):
            return False
        if isinstance(v, int):
            return lo <= v <= hi
        if isinstance(v, str) and v.strip().lstrip("-").isdigit():
            return lo <= int(v) <= hi
        return False
    return ok


# MaxMind license keys look like base64-ish strings of length 30-80.
# We don't try to validate the exact shape — MaxMind could change it.
# Just bound the length to keep someone from pasting in a 10MB file.
def _maxmind_license_key(v):
    return isinstance(v, str) and 0 <= len(v) <= 200


def _maxmind_account_id(v):
    # Stored as int OR as the string form the admin UI submits.
    # Account IDs are 6-8 digit numbers in MaxMind's UI.
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return 1 <= v <= 99_999_999
    if isinstance(v, str):
        return v.strip().isdigit() and 1 <= len(v.strip()) <= 8
    return False


def _cron_expression(v):
    """Validate a 5-field cron expression for geoip.refresh_schedule.

    Delegates to the geoip.scheduler's validator (which also caps the
    fire frequency at 24/day to prevent MaxMind rate-limit issues).
    Doing it here means a bad expression is rejected at PATCH time
    rather than silently failing the next time cron fires.
    """
    if not isinstance(v, str):
        return False
    from app.services.geoip.scheduler import validate_expression
    ok, _ = validate_expression(v)
    return ok


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
    "assistant.widget_subtitle":         _optional_str(200),
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
    # GeoIP feature (PR-A). License key is the secret; account_id is
    # not secret by itself but pointless without the key. Refresh_enabled
    # is the kill switch for the monthly cron in case MaxMind has
    # an outage and we want to silence the noisy log spam temporarily.
    # trusted_proxy_count is documented in app/services/geoip/ip_extraction.py;
    # cpmai's deployment has exactly one proxy hop (Caddy), but the knob
    # exists so a future architecture change (Cloudflare in front of Caddy)
    # is a settings change rather than a code change.
    "geoip.maxmind_account_id":          _maxmind_account_id,
    "geoip.maxmind_license_key":         _maxmind_license_key,
    "geoip.refresh_enabled":             _bool,
    "geoip.refresh_schedule":            _cron_expression,
    "geoip.trusted_proxy_count":         _int_str_in(1, 10),
}


MASK_PLACEHOLDER = "••••"
LAST_FOUR_CHARS = 4


def _mask_value(value):
    """Return the value with only the last 4 chars revealed.

    "Wfpm41_0…6e4f" → "••••6e4f". Empty/None becomes "" (so the
    frontend renders "unset" rather than an opaque bullet block).
    The masked value carries enough signal for an admin to confirm
    they're looking at the right key (the last 4 are stable across
    page loads) without exposing the secret in the GET payload, in
    browser dev tools, or in proxy access logs.
    """
    if value is None or value == "":
        return ""
    s = str(value)
    if len(s) <= LAST_FOUR_CHARS:
        return MASK_PLACEHOLDER + s
    return MASK_PLACEHOLDER + s[-LAST_FOUR_CHARS:]


def _to_setting_out(row) -> SettingOut:
    """Convert a SystemSetting ORM row to the public SettingOut shape,
    applying secret-masking where appropriate.

    The "is this key secret" decision combines TWO sources:
      1. The row's persisted ``is_secret`` flag (set on insert).
      2. The compile-time SECRET_KEYS frozenset.

    The second is the source of truth for newly-registered secret keys
    (e.g. if a deploy adds a secret key but the DB row pre-existed with
    is_secret=False, we still mask). On the next PATCH we also fix the
    row's flag, so the two converge over time.
    """
    is_secret = bool(getattr(row, "is_secret", False)) or row.key in SECRET_KEYS
    value = _mask_value(row.value) if is_secret else row.value
    return SettingOut(
        key=row.key,
        value=value,
        description=row.description,
        updated_at=row.updated_at,
        is_secret=is_secret,
    )


@router.get("", response_model=list[SettingOut])
def list_settings(db: Session = Depends(get_db)):
    return [_to_setting_out(row) for row in settings_store.all(db)]


@router.patch("/{key}", response_model=SettingOut)
def update_setting(key: str, payload: SettingUpdate,
                   db: Session = Depends(get_db),
                   admin: User = Depends(get_admin_user)):
    if key not in EDITABLE:
        raise ValidationError(f"Setting '{key}' is not editable via API.")
    if not EDITABLE[key](payload.value):
        raise ValidationError("Value failed validation for this setting.")
    settings_store.set(key, payload.value, db=db, updated_by=admin.id)

    # Keep the row's ``is_secret`` flag in sync with the compile-time
    # SECRET_KEYS list. settings_store.set() doesn't touch this flag,
    # so we do it here. Idempotent (same value on every write).
    is_secret = key in SECRET_KEYS
    from app.models.system_setting import SystemSetting
    row = db.get(SystemSetting, key)
    if row is not None and row.is_secret != is_secret:
        row.is_secret = is_secret
        db.commit()

    # Audit: log the KEY but never the VALUE for secret keys. The
    # whole point of marking them secret is to keep them out of logs.
    audit_log(db, admin.id, "setting.updated",
              {"key": key,
               "value": "<redacted>" if is_secret else payload.value})

    # Echo back the masked form for secret keys — consistent with GET.
    return SettingOut(
        key=key,
        value=_mask_value(payload.value) if is_secret else payload.value,
        is_secret=is_secret,
    )
