"""Tests for the keyword-based intent classifier — admin-configurable
default fallthrough AND admin-configurable per-intent keyword lists.

Two layers of admin tunability:

  * Default fallthrough — ``assistant.classifier.default_intent``
    (the intent picked when no keyword matched anything).
  * Per-intent keyword lists — ``assistant.classifier.keywords.{intent}``
    (the substrings each intent matches against).

Pins both layers PLUS the malformed-input fallback so an operator
who fat-fingers a setting doesn't take routing down.
"""
import pytest

from app.services.assistant.intent_classifier import Intent, IntentClassifier


@pytest.fixture
def stub_settings(monkeypatch):
    """Minimal settings_store stub — patches both ``get`` (used by
    the per-intent keyword lookup, which expects a JSON list) and
    ``get_str`` (used by the default-intent lookup, which expects a
    string). Tests set values by mutating the returned dict."""
    values: dict[str, object] = {}

    def fake_get(_self, key: str, default=None):
        return values.get(key, default)

    def fake_get_str(_self, key: str, default: str = "") -> str:
        v = values.get(key, default)
        return v if isinstance(v, str) else default

    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",     fake_get)
    monkeypatch.setattr(ss_module.SettingsStore, "get_str", fake_get_str)
    return values


@pytest.fixture
def classifier():
    return IntentClassifier()


# ============================================================ keyword matching

def test_account_keyword_routes_to_account(classifier, stub_settings):
    intent, _ = classifier.classify("Can I get a refund?", [])
    assert intent == Intent.ACCOUNT


def test_content_keyword_routes_to_content(classifier, stub_settings):
    intent, _ = classifier.classify("Explain CPMAI Phase 3", [])
    assert intent == Intent.CONTENT


def test_pmi_keyword_routes_to_pmi_reference(classifier, stub_settings):
    intent, _ = classifier.classify("Where do I register for the exam?", [])
    assert intent == Intent.PMI_REFERENCE


# ============================================================ default fallthrough

def test_unknown_question_falls_through_to_default_content(
        classifier, stub_settings):
    """Pin the default-of-default. With no operator override, an off-
    keyword question routes to CONTENT — the broader handler (broader
    SYSTEM, broader retrieval, the one operators customise)."""
    intent, confidence = classifier.classify("What are GDPR Rules?", [])
    assert intent == Intent.CONTENT
    # Lower confidence than a keyword match (0.4 vs 0.85) — the
    # downstream code can use this to apply different behavior on
    # low-confidence routes (e.g. broader retrieval).
    assert confidence == 0.4


def test_default_intent_is_admin_configurable(classifier, stub_settings):
    """Operator can flip the default back to FAQ (legacy behavior) or
    any other intent without a code deploy. This is the headline
    feature."""
    stub_settings["assistant.classifier.default_intent"] = "faq"
    intent, _ = classifier.classify("What are GDPR Rules?", [])
    assert intent == Intent.FAQ


def test_default_intent_accepts_any_known_intent_value(
        classifier, stub_settings):
    """All five Intent enum values must be selectable via the setting.
    Pin them so adding a new Intent without updating the validator
    doesn't silently leave it unselectable."""
    for raw, expected in [
        ("account",       Intent.ACCOUNT),
        ("faq",           Intent.FAQ),
        ("content",       Intent.CONTENT),
        ("insights",      Intent.INSIGHTS),
        ("pmi_reference", Intent.PMI_REFERENCE),
    ]:
        stub_settings["assistant.classifier.default_intent"] = raw
        intent, _ = classifier.classify("xyz off-keyword", [])
        assert intent == expected, (
            f"setting '{raw}' should resolve to {expected}, got {intent}")


def test_default_intent_invalid_value_falls_back_to_content(
        classifier, stub_settings):
    """Operator typo / dropped value / hand-edited DB row: don't take
    down routing. Fall back to the safest default (CONTENT — broadest
    retrieval). Pin so a future refactor doesn't accidentally start
    raising."""
    stub_settings["assistant.classifier.default_intent"] = "not_a_real_intent"
    intent, _ = classifier.classify("xyz off-keyword", [])
    assert intent == Intent.CONTENT


def test_default_intent_case_insensitive(classifier, stub_settings):
    """Operator might save 'FAQ' or 'Content' with capitals. Don't
    punish minor casing differences."""
    stub_settings["assistant.classifier.default_intent"] = "FAQ"
    intent, _ = classifier.classify("xyz off-keyword", [])
    assert intent == Intent.FAQ


# ============================================================ tunable keywords

def test_admin_can_add_a_keyword_to_route_a_previously_unmatched_question(
        classifier, stub_settings):
    """The headline use case. The shipped FAQ list does NOT contain
    'cost' — so "How Much Does CPMAI Cost?" falls through to the
    default (content) handler today, where the answer isn't. Admin
    adds 'cost' to the FAQ keywords; the same question now routes
    to FAQ. This is the legacy-side fix for the cost-question
    debugging session."""
    # Baseline: with the shipped defaults, cost question falls to default.
    intent_before, _ = classifier.classify("How Much Does CPMAI Cost?", [])
    assert intent_before == Intent.CONTENT   # default

    # Admin extends FAQ keywords.
    stub_settings["assistant.classifier.keywords.faq"] = [
        "exam pattern", "passing", "duration", "fee", "cost",
        "eligibility", "certification",
    ]
    intent_after, _ = classifier.classify("How Much Does CPMAI Cost?", [])
    assert intent_after == Intent.FAQ


def test_admin_can_clear_keywords_to_silence_an_intent(
        classifier, stub_settings):
    """Empty list = this intent never matches via keyword. Useful if
    an intent's keywords are mis-routing common questions and the
    operator wants to disable that intent's keyword matching while
    keeping the handler available via the default fallthrough."""
    stub_settings["assistant.classifier.keywords.insights"] = []
    # "improve" normally routes to INSIGHTS — with INSIGHTS keywords
    # cleared, falls through to ACCOUNT/CONTENT keyword scan instead.
    intent, _ = classifier.classify("how can I improve my data?", [])
    assert intent != Intent.INSIGHTS


def test_keywords_are_lowercased_at_read_time(classifier, stub_settings):
    """The admin form preserves whatever case the operator typed.
    The classifier lowercases both the message and each keyword at
    read time, so 'COST' typed in admin matches 'cost' in messages
    and vice-versa."""
    stub_settings["assistant.classifier.keywords.faq"] = ["COST", "FEE"]
    # Message is already lowercased internally — uppercase keyword
    # still matches.
    intent, _ = classifier.classify("how much does CPMAI cost?", [])
    assert intent == Intent.FAQ


def test_malformed_keyword_value_falls_back_to_hardcoded(
        classifier, stub_settings):
    """Admin saved something that's not a list (e.g. a JSON string
    instead of an array, or null after a hand-edited DB row). Don't
    blow up routing — fall back to the hardcoded defaults so the
    chat path keeps working."""
    stub_settings["assistant.classifier.keywords.account"] = "not a list"
    intent, _ = classifier.classify("Can I get a refund?", [])
    # Hardcoded ACCOUNT list contains 'refund' → fallback works.
    assert intent == Intent.ACCOUNT


def test_non_string_entries_in_list_are_skipped(classifier, stub_settings):
    """An accidentally-typed integer or null in the list doesn't
    block the rest of the list from matching."""
    stub_settings["assistant.classifier.keywords.faq"] = [
        "exam pattern", 42, None, "cost",
    ]
    intent, _ = classifier.classify("How Much Does CPMAI Cost?", [])
    # 'cost' is the only valid match-able string after filtering.
    assert intent == Intent.FAQ


def test_priority_order_is_preserved_when_admin_overrides_keywords(
        classifier, stub_settings):
    """The priority order (PMI > INSIGHTS > ACCOUNT > CONTENT > FAQ)
    is hardcoded. Even if admin gives ACCOUNT and FAQ both a keyword
    that matches the same message, ACCOUNT (higher priority) wins."""
    stub_settings["assistant.classifier.keywords.account"] = ["foo"]
    stub_settings["assistant.classifier.keywords.faq"]     = ["foo"]
    intent, _ = classifier.classify("question about foo", [])
    assert intent == Intent.ACCOUNT   # higher priority


def test_per_intent_keyword_lookup_is_independent(classifier, stub_settings):
    """Overriding one intent's keywords doesn't affect the others.
    The other 4 intents keep using their hardcoded defaults."""
    stub_settings["assistant.classifier.keywords.faq"] = ["only this"]
    # Default ACCOUNT keywords still work — "refund" is in the
    # shipped list and we didn't touch ACCOUNT.
    intent, _ = classifier.classify("I want a refund", [])
    assert intent == Intent.ACCOUNT
