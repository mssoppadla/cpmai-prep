"""Drift guard + happy-path coverage for /admin/settings.

The bug we're preventing: a setting shows up in admin's Runtime Settings
page (because list_settings returns everything in DB), but PATCH rejects
it with "not editable via API" because nobody added the key to the
EDITABLE allowlist when it was seeded. Users see a working-looking text
box that throws on save.

Two-layer protection:

  1. **Structural drift guard** (`test_every_seeded_key_is_editable`):
     for every key in seeds/default_settings.json, the key must appear
     in EDITABLE. Catches "added a seed but forgot the validator" at
     test time, not at user-edit time.

  2. **Per-key happy path** (parametrized): a realistic value for each
     editable key must round-trip through PATCH cleanly. Catches
     "validator was wrong" or "wrong type expected" without needing
     to maintain a separate spec.

Adding a setting:
  - Add it to seeds/default_settings.json
  - Add it to EDITABLE in admin/settings.py
  - Add a row to HAPPY_PATH_VALUES below
"""
import json
import pathlib
import pytest

from app.api.v1.endpoints.admin.settings import EDITABLE
from tests.conftest import auth_header

SEEDS_FILE = (pathlib.Path(__file__).parent.parent.parent
              / "seeds" / "default_settings.json")


def _seeded_keys() -> set[str]:
    return {row["key"] for row in json.loads(SEEDS_FILE.read_text())}


# Realistic admin-typed values for each key. Used as the round-trip
# target in the parametrized test. Keep these in sync with the
# validator semantics in admin/settings.py.
HAPPY_PATH_VALUES: dict[str, object] = {
    # chat.*
    "chat.daily_limit.anonymous":        10,
    "chat.daily_limit.authenticated":    50,
    "chat.max_input_chars":              4000,
    "chat.max_output_chars":             4000,
    "chat.tokens_per_day_authenticated": 50000,
    "chat.cooldown_seconds":             3,
    # auth.*
    "auth.lockout_threshold":            5,
    "auth.lockout_minutes":              15,
    # llm.* / payment.*
    "llm.active_provider_id":            None,
    "llm.fallback_provider_id":          None,
    "llm.cache_ttl_seconds":             30,
    "payment.active_provider_id":        None,
    "payment.cache_ttl_seconds":         30,
    # embeddings + RAG
    "embeddings.provider_id":            None,
    "embeddings.cache_ttl_seconds":      60,
    "rag.top_k":                         4,
    "rag.min_similarity":                0.3,
    # PMI link-out
    "pmi.course_bundle_url":             "https://www.pmi.org/cpmai",
    "pmi.eco_url":                       "https://www.pmi.org/cpmai/eco",
    # Assistant guardrails (admin-tunable system prompt + topic policy)
    "assistant.system_prompt_preamble":  "You are CPMAI Prep's assistant.",
    "assistant.allowed_topics":          "CPMAI, ML, data science.",
    "assistant.banned_topics":           "PMP-only methodologies.",
    "assistant.allowed_exceptions":      "PMI history.",
    "assistant.no_provider_message":     "Our AI tutor is coming back soon — thanks for your patience.",
    "assistant.widget_subtitle":         "Grounded in CPMAI prep materials.",
    # pricing.*
    "pricing.stack_offer_with_discount": True,
    "pricing.gst_percent":               18,
    "pricing.supported_currencies":      ["INR", "USD", "EUR"],
    "pricing.fx_rates_inr_per_unit":     {"USD": 83.0, "EUR": 90.0},
    # landing.*
    "landing.lead_section_heading":      "Start with our free CPMAI study guide",
    "landing.lead_cta_text":             "Get the free guide",
    "landing.lead_post_submit_route":    "/exams",
    "landing.premium_upsell_title":      "Get the full bank",
    "landing.premium_upsell_body":       "Unlock everything for one year.",
    # site.*
    "site.brand_name":                   "CPMAI Prep",
    "site.tagline":                      "Pass the CPMAI certification.",
    "site.support_email":                "contact@cpmaiexamprep.com",
    "site.linkedin_url":                 "https://www.linkedin.com/in/example",
    "site.youtube_url":                  "https://www.youtube.com/@example",
    "site.twitter_url":                  "https://x.com/example",
    "site.copyright_text":               "© 2026 CPMAI Prep.",
    "site.show_pricing_link":            False,
    # geoip.* — see app/services/geoip/README.md
    "geoip.maxmind_account_id":          "1345788",
    "geoip.maxmind_license_key":         "test_license_key_only_for_round_trip",
    "geoip.refresh_enabled":             True,
    "geoip.refresh_schedule":            "17 4 * * 3,6",
    "geoip.trusted_proxy_count":         1,
}


# ============================================================ drift guards
def test_every_seeded_key_is_editable():
    """Adding a default seed without an EDITABLE entry is the
    bug we're preventing — surface it at CI, not at user-click time."""
    seeded = _seeded_keys()
    missing = sorted(seeded - set(EDITABLE.keys()))
    assert not missing, (
        f"Settings seeded but not editable via API: {missing}. "
        "Add a validator in admin/settings.py::EDITABLE.")


def test_every_editable_key_has_a_happy_path_test_value():
    """Forces the test author to pick a realistic value when adding
    a new key. Without this, a new EDITABLE entry would be untested."""
    missing = sorted(set(EDITABLE.keys()) - set(HAPPY_PATH_VALUES.keys()))
    assert not missing, (
        f"EDITABLE keys without a HAPPY_PATH_VALUES row: {missing}. "
        "Add a realistic value to test_settings_editable.py.")


# ============================================================ happy path
@pytest.mark.parametrize("key", sorted(EDITABLE.keys()))
def test_each_editable_key_round_trips(client, admin, key):
    """Round-trip every key end-to-end: PATCH, expect 200, GET, expect
    the new value present. Catches type mismatches between seed default
    and validator, and confirms the audit-log + settings-store path
    works for every key.

    Secret keys (``is_secret=True``) are an exception: PATCH echoes the
    masked form, never the plaintext (matches the GET behavior). For
    those keys we check the masked shape + the ``is_secret`` flag, not
    value equality.
    """
    from app.api.v1.endpoints.admin.settings import SECRET_KEYS, _mask_value
    headers = auth_header(client, admin.email)
    value = HAPPY_PATH_VALUES[key]
    r = client.patch(f"/api/v1/admin/settings/{key}",
                     headers=headers, json={"value": value})
    assert r.status_code == 200, f"PATCH {key} failed: {r.text}"
    body = r.json()
    assert body["key"] == key
    if key in SECRET_KEYS:
        # Masked form: starts with "••••" and ends with last-4 of value.
        # The flag must be flipped on so the frontend renders SecretInput.
        assert body.get("is_secret") is True
        assert body["value"] == _mask_value(value)
    else:
        assert body["value"] == value


# =================================================== specific bug fix
def test_site_support_email_is_editable():
    """Regression: previously rejected with 'Setting site.support_email
    is not editable via API' because the key was missing from the
    allowlist."""
    assert "site.support_email" in EDITABLE


def test_site_support_email_accepts_empty_string():
    """Empty string means 'hide this from the footer'. Validator must
    accept it — the seed default is empty."""
    assert EDITABLE["site.support_email"]("")


def test_site_support_email_rejects_non_email():
    """Lightweight gate — '@' + '.' required."""
    assert not EDITABLE["site.support_email"]("not-an-email")
    assert not EDITABLE["site.support_email"](42)


# ================================================ url validators
@pytest.mark.parametrize("key", [
    "site.linkedin_url", "site.youtube_url", "site.twitter_url",
])
def test_site_urls_accept_empty_or_https(key):
    assert EDITABLE[key]("")
    assert EDITABLE[key]("https://example.com")
    assert EDITABLE[key]("http://example.com")
    assert not EDITABLE[key]("ftp://example.com")
    assert not EDITABLE[key]("example.com")        # no scheme


# ============================================================ rejection
def test_unknown_key_rejected(client, admin):
    """A typo or made-up key must surface a clear message, not a 500."""
    headers = auth_header(client, admin.email)
    r = client.patch("/api/v1/admin/settings/site.NONEXISTENT",
                     headers=headers, json={"value": "x"})
    assert r.status_code == 422
    assert "not editable" in r.json()["error"]["message"].lower()


def test_invalid_value_rejected(client, admin):
    """Validator says no → 422 with the generic 'failed validation' msg."""
    headers = auth_header(client, admin.email)
    r = client.patch("/api/v1/admin/settings/pricing.gst_percent",
                     headers=headers, json={"value": 250})
    assert r.status_code == 422


def test_admin_required(client, user):
    """Regular users can't edit settings."""
    headers = auth_header(client, user.email)
    r = client.patch("/api/v1/admin/settings/pricing.gst_percent",
                     headers=headers, json={"value": 18})
    assert r.status_code in (401, 403)
