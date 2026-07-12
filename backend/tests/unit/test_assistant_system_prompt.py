"""Tests for the admin-configurable guardrail preamble assembly.

This file pins the contract for the four admin settings that compose
the assistant's system-prompt preamble:

  - assistant.system_prompt_preamble  (persona)
  - assistant.allowed_topics          (in-scope subjects)
  - assistant.allowed_exceptions      (ADDITIONAL in-scope subjects)
  - assistant.banned_topics           (refused subjects)

The original allowed_exceptions wiring had two bugs:

  1. The exceptions block was gated behind `banned_topics` being set —
     so an admin who added "GDPR Rules" to exceptions with no banned
     topics configured saw their exception silently dropped.
  2. The exceptions block only extended the banned-list carve-out,
     not the allowed_topics whitelist. So even with banned set, the
     LLM would still refuse the topic for not being in allowed_topics.

Both were reported by an operator on 2026-05-14. Fixed by promoting
exceptions to a top-level "ALSO ALLOWED" block that's independent of
both lists. These tests pin the corrected contract.
"""
import pytest

from app.services.assistant import system_prompt


@pytest.fixture
def stub_settings(monkeypatch):
    """Drop-in replacement for settings_store.get_str — returns whatever
    the test sets up, defaulting to empty string. Lets each test
    isolate exactly which guardrail keys are active."""
    values: dict[str, str] = {}

    def fake_get_str(key: str, default: str = "") -> str:
        return values.get(key, default)

    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get_str",
                        lambda self, k, d="": fake_get_str(k, d))
    return values


# ============================================================ empty defaults

def test_empty_settings_yield_empty_preamble(stub_settings):
    """No keys set → no preamble. Handlers prepend an empty string,
    which is a no-op."""
    assert system_prompt.assemble_preamble() == ""


def test_with_preamble_always_carries_privacy_directive(stub_settings):
    """Even with EVERY admin setting empty, the non-removable privacy
    directive is prepended — data isolation must not depend on admin
    configuration. The handler's own prompt stays intact at the end."""
    result = system_prompt.with_preamble("HANDLER PROMPT")
    assert result.endswith("HANDLER PROMPT")
    assert system_prompt.PRIVACY_DIRECTIVE in result
    assert "Never disclose information about any user other than" in result


# ============================================================ each piece alone

def test_only_persona_renders(stub_settings):
    stub_settings["assistant.system_prompt_preamble"] = "You are a helpful tutor."
    out = system_prompt.assemble_preamble()
    assert "You are a helpful tutor." in out
    assert "TOPIC SCOPE" not in out
    assert "BANNED" not in out
    assert "ALSO ALLOWED — " not in out


def test_only_allowed_topics_renders_topic_scope(stub_settings):
    stub_settings["assistant.allowed_topics"] = "CPMAI, data science"
    out = system_prompt.assemble_preamble()
    assert "TOPIC SCOPE" in out
    assert "CPMAI, data science" in out
    assert "BANNED" not in out
    assert "ALSO ALLOWED — " not in out


def test_only_banned_topics_renders_banned_block(stub_settings):
    """The BANNED section now cross-references ALSO ALLOWED in its body
    text (so the LLM knows what to do if a subject is in both). That's
    a substring of the literal — the assertion below checks for the
    SECTION HEADER specifically, not any occurrence of the phrase."""
    stub_settings["assistant.banned_topics"] = "PMP-only methodologies"
    out = system_prompt.assemble_preamble()
    assert "BANNED" in out
    assert "PMP-only methodologies" in out
    assert "TOPIC SCOPE" not in out
    # Section headers start with "ALSO ALLOWED — " (em-dash). The cross-
    # reference inside the banned block uses "ALSO ALLOWED list", which
    # this assertion deliberately doesn't match.
    assert "ALSO ALLOWED — " not in out


# ====================================================== the headline bug fix

def test_allowed_exceptions_renders_without_banned_topics(stub_settings):
    """REGRESSION GUARD: the original bug. Admin set
    `allowed_exceptions = "GDPR Rules"` with no banned_topics. The
    exception silently disappeared from the prompt → LLM refused GDPR
    questions because the topic wasn't in allowed_topics either.

    Fix: exceptions render as a top-level "ALSO ALLOWED" block
    regardless of whether banned_topics is set."""
    stub_settings["assistant.allowed_exceptions"] = "GDPR Rules"
    out = system_prompt.assemble_preamble()
    assert "ALSO ALLOWED" in out
    assert "GDPR Rules" in out


def test_allowed_exceptions_overrides_narrow_allowed_topics(stub_settings):
    """The second half of the bug: allowed_exceptions should bring a
    topic INTO scope even when allowed_topics is a narrow whitelist.

    Without this, an admin with a tight allowed_topics ("CPMAI only")
    couldn't unlock GDPR without rewriting the entire scope statement —
    which is exactly the use case the exceptions field is meant to
    serve."""
    stub_settings["assistant.allowed_topics"] = "CPMAI Body of Knowledge only"
    stub_settings["assistant.allowed_exceptions"] = "GDPR Rules, AI Act"
    out = system_prompt.assemble_preamble()
    # Both blocks render.
    assert "TOPIC SCOPE" in out
    assert "ALSO ALLOWED" in out
    assert "CPMAI Body of Knowledge only" in out
    assert "GDPR Rules, AI Act" in out
    # ALSO ALLOWED wording must give the LLM unambiguous "don't refuse"
    # signals. Earlier soft wording ("these subjects ARE in scope")
    # didn't stop gpt-4o-mini from refusing — see the classifier-default
    # hotfix docstring for the operator-reported repro. Pin the
    # imperative anti-refusal phrasing.
    lowered = out.lower()
    assert "do not decline" in lowered, (
        "ALSO ALLOWED block must explicitly tell the LLM not to "
        "decline — without this the model anchors to whatever narrower "
        "framing the handler-level SYSTEM prompt provides")
    assert "regardless" in lowered, (
        "ALSO ALLOWED must make clear these topics override narrower "
        "framing in the rest of the prompt")


def test_allowed_exceptions_overrides_banned_topics(stub_settings):
    """When a topic is in BOTH banned and exceptions, the exception
    wins (the field name 'allowed_exceptions' implies an exception TO
    the banned list, which is the original intent — we preserve it)."""
    stub_settings["assistant.banned_topics"] = "EU regulations"
    stub_settings["assistant.allowed_exceptions"] = "GDPR Rules"
    out = system_prompt.assemble_preamble()
    # Both blocks render.
    assert "BANNED" in out
    assert "ALSO ALLOWED" in out
    # The banned block must mention that ALSO ALLOWED takes precedence
    # so the LLM knows what to do when a subject is in both lists.
    banned_idx = out.find("BANNED")
    assert banned_idx >= 0
    banned_section = out[banned_idx:]
    assert ("ALSO ALLOWED" in banned_section
            or "unless" in banned_section.lower()
            or "except" in banned_section.lower())


# ============================================================ full assembly

def test_full_preamble_has_all_four_pieces_in_order(stub_settings):
    """End-to-end: every guardrail field set. They must all render and
    appear in a stable order so the LLM sees them consistently."""
    stub_settings["assistant.system_prompt_preamble"] = "PERSONA"
    stub_settings["assistant.allowed_topics"]        = "SCOPE_ITEMS"
    stub_settings["assistant.allowed_exceptions"]    = "EXCEPTION_ITEMS"
    stub_settings["assistant.banned_topics"]         = "BANNED_ITEMS"

    out = system_prompt.assemble_preamble()
    # All four pieces present.
    assert "PERSONA" in out
    assert "SCOPE_ITEMS" in out
    assert "EXCEPTION_ITEMS" in out
    assert "BANNED_ITEMS" in out
    # Order matters for LLM reading: persona first, scope, then
    # ALSO ALLOWED (so it's read before BANNED), then BANNED.
    assert (out.find("PERSONA")
            < out.find("SCOPE_ITEMS")
            < out.find("EXCEPTION_ITEMS")
            < out.find("BANNED_ITEMS"))


def test_with_preamble_concatenates_handler_prompt(stub_settings):
    """The convenience wrapper appends the handler's intent-specific
    system to the assembled guardrails."""
    stub_settings["assistant.allowed_topics"] = "CPMAI"
    full = system_prompt.with_preamble("HANDLER SPECIFIC GUIDANCE")
    assert "CPMAI" in full
    assert "HANDLER SPECIFIC GUIDANCE" in full
    # Guardrails come BEFORE the handler prompt.
    assert full.index("CPMAI") < full.index("HANDLER SPECIFIC GUIDANCE")


# ============================================================ configurable_handler_system

def test_configurable_handler_system_returns_fallback_when_unset(stub_settings):
    """Empty / missing setting → use the handler's hardcoded default.
    Pre-condition for safe rollout: every handler ships with a working
    fallback so an admin who's never touched the setting still gets
    the expected behavior."""
    out = system_prompt.configurable_handler_system(
        "faq", "fallback prompt for FAQ")
    assert out == "fallback prompt for FAQ"


def test_configurable_handler_system_returns_admin_value_when_set(stub_settings):
    """Admin-saved value wins over the fallback. This is the headline
    feature — operator iteration on prompts without code deploys."""
    stub_settings["assistant.handler.faq.system"] = "ADMIN-CUSTOM FAQ PROMPT"
    out = system_prompt.configurable_handler_system(
        "faq", "fallback prompt")
    assert out == "ADMIN-CUSTOM FAQ PROMPT"


def test_configurable_handler_system_falls_back_on_whitespace_only(stub_settings):
    """Whitespace-only saved value treated as 'unset' — operator can't
    accidentally save a blank prompt and silently break the bot."""
    stub_settings["assistant.handler.content.system"] = "   \n\t  \n"
    out = system_prompt.configurable_handler_system(
        "content", "fallback content prompt")
    assert out == "fallback content prompt"


def test_allowed_exceptions_directive_uses_default_when_unset(stub_settings):
    """Empty / unset directive setting → strong hardcoded default
    appears in the rendered prompt. This is the operator-friendly
    default: get the strong anti-refusal language without having to
    write it themselves."""
    stub_settings["assistant.allowed_exceptions"] = "GDPR Rules"
    out = system_prompt.assemble_preamble()
    lowered = out.lower()
    assert "do not decline" in lowered, (
        "Default directive must include 'Do NOT decline' — that's the "
        "imperative wording that defeats LLM conservatism")
    assert "gdpr rules" in lowered


def test_allowed_exceptions_directive_uses_admin_value_when_set(stub_settings):
    """Admin-saved directive wins over the hardcoded default. Operator
    knob for tuning prompt style per LLM (e.g. softer language for
    Sonnet which doesn't need the imperative tone)."""
    stub_settings["assistant.allowed_exceptions"] = "Compliance"
    stub_settings["assistant.allowed_exceptions_directive"] = (
        "POLICY (custom): Answer freely about the following subjects.")
    out = system_prompt.assemble_preamble()
    assert "POLICY (custom):" in out
    assert "Compliance" in out
    # Default wording must NOT appear — admin's override fully replaces.
    assert "Do NOT decline" not in out


def test_allowed_exceptions_directive_whitespace_only_falls_back(stub_settings):
    """Whitespace-only saved value treated as 'unset' — operator can't
    accidentally save a blank directive and weaken the prompt."""
    stub_settings["assistant.allowed_exceptions"] = "GDPR"
    stub_settings["assistant.allowed_exceptions_directive"] = "   \n\t  "
    out = system_prompt.assemble_preamble()
    assert "do not decline" in out.lower()


def test_configurable_handler_system_uses_correct_key_per_handler(stub_settings):
    """The key shape is ``assistant.handler.{name}.system`` — pin it,
    because the admin UI and seed JSON encode the same convention.
    Renaming the convention without updating both surfaces silently
    breaks the wiring."""
    stub_settings["assistant.handler.account.system"] = "ACCOUNT-SPECIFIC"
    stub_settings["assistant.handler.insights.system"] = "INSIGHTS-SPECIFIC"
    assert system_prompt.configurable_handler_system(
        "account", "x") == "ACCOUNT-SPECIFIC"
    assert system_prompt.configurable_handler_system(
        "insights", "x") == "INSIGHTS-SPECIFIC"
    # A handler with no override falls through.
    assert system_prompt.configurable_handler_system(
        "faq", "FAQ-FALLBACK") == "FAQ-FALLBACK"
