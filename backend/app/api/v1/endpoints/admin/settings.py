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


def _short_str_list(*, max_items: int = 20, max_item_len: int = 200):
    """List of non-empty strings, e.g. the assistant "try asking" suggestions.

    Each entry: 1..max_item_len chars after strip.
    Whole list: 0..max_items entries (empty list disables the feature).
    """
    def ok(v):
        if not isinstance(v, list):
            return False
        if len(v) > max_items:
            return False
        for entry in v:
            if not isinstance(entry, str):
                return False
            s = entry.strip()
            if not (1 <= len(s) <= max_item_len):
                return False
        return True
    return ok


def _float_in(lo: float, hi: float):
    return lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def _is_flow_value(v) -> bool:
    """Validate ``assistant.flow``.

    Accepts the four canonical orchestration-flow strings plus the
    ``percent:N`` cohort form (N integer 0..100). Anything else gets
    rejected at PATCH; the runtime resolver also falls back to
    ``legacy`` on malformed values as a defence-in-depth measure.

    Why allow ``percent:0`` and ``percent:100``: they're the natural
    end-points of a gradual rollout — 0 means "I want to enable the
    setting but keep agentic off", 100 means "fully rolled out, ready
    to switch to plain 'agentic' on the next save".
    """
    if not isinstance(v, str):
        return False
    s = v.strip().lower()
    if s in {"legacy", "agentic", "shadow"}:
        return True
    if s.startswith("percent:"):
        try:
            n = int(s.split(":", 1)[1])
        except ValueError:
            return False
        return 0 <= n <= 100
    return False


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


def _supported_currencies(v):
    """Validate ``pricing.supported_currencies`` — JSON array of ISO-4217.

    Constraints:
      * Must be a non-empty list of distinct 3-letter uppercase codes
      * Must include "INR" (the canonical pricing currency — Plan.base_price_paise
        is denominated in INR and FX conversion is INR-relative)
      * Each code is 3 alpha chars (basic ISO-4217 shape; we don't pull
        the full ISO table — admin error budget is small here)
      * Cap at 20 currencies to prevent a typo'd huge list from breaking
        the picker UI
    """
    if not isinstance(v, list):
        return False
    if not 1 <= len(v) <= 20:
        return False
    seen = set()
    for code in v:
        if not isinstance(code, str):
            return False
        c = code.strip().upper()
        if len(c) != 3 or not c.isalpha() or c in seen:
            return False
        seen.add(c)
    return "INR" in seen


def _fx_rates(v):
    """Validate ``pricing.fx_rates_inr_per_unit`` — JSON object of FX rates.

    Each key: 3-letter ISO-4217 code. Each value: positive float (INR
    per 1 unit of that currency, e.g. {"USD": 83} means 1 USD = 83 INR).
    Reasonable upper bound = 100_000 (catches a fat-fingered "83000"
    that would price USD-paying users out of existence). Lower bound =
    0.0001 (prevents zero / negative which would crash the divide).

    The INR rate itself is implicit (always 1.0). Admins can include
    or omit it; the consumer treats it as 1 in either case.
    """
    if not isinstance(v, dict):
        return False
    if len(v) > 50:   # sanity cap
        return False
    for code, rate in v.items():
        if not isinstance(code, str) or len(code.strip()) != 3 or not code.strip().isalpha():
            return False
        if isinstance(rate, bool):    # bool is a subtype of int, reject
            return False
        if not isinstance(rate, (int, float)):
            return False
        if not (0.0001 <= float(rate) <= 100_000):
            return False
    return True


def _fx_overrides(v):
    """Validate ``pricing.fx_overrides`` — admin-set rates that win
    over live FX. Same shape as ``pricing.fx_rates_inr_per_unit``
    (kept as a separate validator only because the two settings have
    different semantics: one is the legacy admin-managed list, the
    other is the new live-bypass list)."""
    return _fx_rates(v) if v else (isinstance(v, dict) and len(v) == 0)


def _fx_live_raw(v):
    """Validate ``pricing.fx_live_raw`` — auto-managed by the cron.

    Admins should NEVER edit this by hand (use ``pricing.fx_overrides``
    instead), but the validator still has to accept what the cron
    writes, which is the same shape as fx_overrides plus an empty
    dict on first deploy. Tolerant of empty input.
    """
    return isinstance(v, dict) and (len(v) == 0 or _fx_rates(v))


def _fx_live_fetched_at(v):
    """ISO-8601 datetime string, or empty string for "never fetched"."""
    if not isinstance(v, str):
        return False
    if v == "":
        return True
    if len(v) > 64:
        return False
    try:
        from datetime import datetime
        datetime.fromisoformat(v)
        return True
    except ValueError:
        return False


def _fx_markup_percent(v):
    """Markup percent the cron applies on top of live mid-market.

    Range 0..50 — anything outside is almost certainly a typo or an
    unwise pricing decision. 5% is the recommended default (covers
    Razorpay's ~3% international FX fee + ~2% drift buffer).
    """
    if isinstance(v, bool):
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return 0.0 <= f <= 50.0


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
    # JWT token lifetimes — bounds also enforced defensively in
    # app/core/security.py (clamp) so a direct-DB edit can't mint
    # zero-second tokens. Lower access if a compromise is suspected.
    "auth.access_token_expire_minutes":  _int_in(5, 1440),
    "auth.refresh_token_expire_days":    _int_in(1, 30),
    # LLM / payment provider plumbing
    "llm.active_provider_id":            lambda v: v is None or isinstance(v, int),
    "llm.fallback_provider_id":          lambda v: v is None or isinstance(v, int),
    "llm.cache_ttl_seconds":             lambda v: isinstance(v, int) and v >= 1,
    "payment.active_provider_id":        lambda v: v is None or isinstance(v, int),
    "payment.non_inr_provider_id":       lambda v: v is None or isinstance(v, int),
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
    # Error message thrown from guardrails when an anonymous request
    # arrives without an anon_id. User-facing — frontend renders verbatim.
    "assistant.anonymous_no_identity_message":
                                         _short_str(500),
    # Starter prompts in the chat widget's empty state. Each one becomes
    # a clickable chip that pre-fills the chat input. Empty list disables
    # the suggestions entirely (just the greeting shows).
    "assistant.try_asking_suggestions":  _short_str_list(
                                            max_items=10, max_item_len=200),
    # Per-handler SYSTEM prompts. Empty string falls back to the
    # handler's hardcoded DEFAULT_SYSTEM in code, so an admin can
    # safely "clear to default" by saving "". Cap is generous (4000)
    # because a SYSTEM prompt may include several paragraphs of
    # instructions, examples, formatting rules.
    "assistant.handler.faq.system":      _optional_str(4000),
    "assistant.handler.content.system":  _optional_str(4000),
    "assistant.handler.account.system":  _optional_str(4000),
    "assistant.handler.insights.system": _optional_str(4000),
    # Drift detection. When true, the orchestrator runs post-checks on
    # every LLM response and writes structured audit_log rows for
    # signatures like "refused with context available", "missing
    # citation when chunks were retrieved", etc. The rows feed
    # /admin/assistant-drift. Off by default during initial rollout
    # so operators don't see noise before tuning.
    "assistant.drift_detection_enabled": _bool,
    # Classifier default fallthrough — which Intent (and therefore
    # which handler) runs when the regex classifier doesn't match
    # any keyword. Defaults to "content"; switch to "faq" for the
    # legacy behavior, or to any Intent enum value name. Malformed
    # values fall back to "content" at runtime.
    "assistant.classifier.default_intent":
        lambda v: isinstance(v, str) and v.lower() in {
            "account", "faq", "content", "insights", "pmi_reference"},
    # Admin-tunable keyword lists for the legacy classifier. Each is
    # a list of substrings the classifier matches case-insensitively
    # against the user's message. Order WITHIN a list does not matter
    # (any match counts); order BETWEEN intents is hardcoded in code
    # (PMI > INSIGHTS > ACCOUNT > CONTENT > FAQ). Empty list = the
    # intent never matches via keyword. Missing setting falls back to
    # the hardcoded default in intent_classifier.py.
    # Cap of 100 entries × 200 chars is generous — typical lists have
    # ~10-15 short substrings.
    "assistant.classifier.keywords.pmi_reference":
        _short_str_list(max_items=100, max_item_len=200),
    "assistant.classifier.keywords.insights":
        _short_str_list(max_items=100, max_item_len=200),
    "assistant.classifier.keywords.account":
        _short_str_list(max_items=100, max_item_len=200),
    "assistant.classifier.keywords.content":
        _short_str_list(max_items=100, max_item_len=200),
    "assistant.classifier.keywords.faq":
        _short_str_list(max_items=100, max_item_len=200),
    # Pre-text injected before the operator's allowed_exceptions list
    # in the system prompt. Empty falls back to the strong hardcoded
    # default ("Do NOT decline... Do NOT apologize..."). Tune for
    # different LLMs — some need more imperative language, others
    # need less. 4000 chars is generous for multi-paragraph prompts.
    "assistant.allowed_exceptions_directive": _optional_str(4000),
    # Agentic toggle — selects orchestration flow.
    #   "legacy"           = current keyword-classifier + handlers pipeline
    #   "agentic"          = router + tool-calling + synthesis
    #   "percent:<0-100>"  = N% of users get agentic (deterministic hash)
    #   "shadow"           = run both, return legacy, log agentic for compare
    # Anything else falls back to "legacy" at runtime (safest default).
    # Validator accepts the four canonical strings plus the percent:N
    # form with N in 0..100.
    "assistant.flow":                        lambda v: _is_flow_value(v),
    # Hard cap on tool calls per agentic turn (including router re-plans).
    # Cost guardrail — keeps a confused router from looping. 1..10 is
    # the sane range; default 4.
    "assistant.agentic.tools_max_calls":     _int_in(1, 10),
    # Admin-tunable router/synthesis system prompts. Empty falls back
    # to the shipped defaults baked into the agentic orchestrator.
    "assistant.agentic.router_system":       _optional_str(8000),
    "assistant.agentic.synthesis_system":    _optional_str(8000),
    # Fraction of shadow-mode requests on which agentic actually runs.
    # 0.0 = shadow disabled, 1.0 = every legacy request also runs agentic.
    "assistant.agentic.shadow_sampling_rate": _float_in(0.0, 1.0),
    # Pricing knobs (phase 1 + 2)
    "pricing.stack_offer_with_discount": _bool,
    "pricing.gst_percent":               _int_in(0, 100),
    # International pricing — admin-tunable currencies + FX rates.
    # See app/services/pricing_service.py for how these flow into a quote.
    # GST only applies to INR; non-INR currencies skip the GST line.
    "pricing.supported_currencies":      _supported_currencies,
    "pricing.fx_rates_inr_per_unit":     _fx_rates,
    # Live FX system — added 2026-05-14 alongside the Frankfurter cron.
    # ``fx_live_raw`` + ``fx_live_fetched_at`` are CRON-MANAGED (admins
    # see them but should rarely edit). ``fx_markup_percent`` and
    # ``fx_overrides`` are the admin-tunable knobs.
    "pricing.fx_live_raw":               _fx_live_raw,
    "pricing.fx_live_fetched_at":        _fx_live_fetched_at,
    "pricing.fx_markup_percent":         _fx_markup_percent,
    "pricing.fx_overrides":              _fx_overrides,
    # Landing-page copy (admin-editable, no redeploy needed)
    "landing.lead_section_heading":      _short_str(200),
    "landing.lead_cta_text":             _short_str(80),
    "landing.lead_post_submit_route":    _short_str(200),
    "landing.premium_upsell_title":      _short_str(120),
    "landing.premium_upsell_body":       _short_str(500),
    # Public landing-page hero. Bigger limits than the marketing-copy
    # blocks above because the headline (h1) AND the subtitle (long
    # supporting sentence) both live here.
    "landing.hero_headline":             _short_str(200),
    "landing.hero_subtitle":             _short_str(500),
    # Exams page anonymous-state banner. Plain text (not markdown),
    # rendered with the same indigo-50 banner styling as before — only
    # the wording changes.
    "exams.anonymous_banner":            _short_str(1000),
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
    # CMS landing-page master switch. When true and a content_page is
    # marked is_landing=true, the public / route serves the CMS page
    # instead of the marketing homepage. See migration 0025 and
    # backend/app/api/v1/endpoints/cms_public.py::cms_landing.
    "cms.use_cms_landing":               _bool,
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
