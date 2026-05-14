"""Tests for the keyword-based intent classifier and its admin-
configurable default fallthrough.

The default fallthrough is the only operator-tunable part of this
classifier (the keyword tables themselves are code-shipped). Pin
both the default value AND the malformed-input fallback so an
admin who fat-fingers the setting field doesn't break routing.
"""
import pytest

from app.services.assistant.intent_classifier import Intent, IntentClassifier


@pytest.fixture
def stub_settings(monkeypatch):
    """Minimal settings_store stub — same shape as the system_prompt
    tests so the patterns stay consistent."""
    values: dict[str, str] = {}

    def fake_get_str(_self, key: str, default: str = "") -> str:
        return values.get(key, default)

    from app.core import settings_store as ss_module
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
