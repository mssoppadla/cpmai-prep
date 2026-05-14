"""Tests for assistant drift-detection rules + audit-log dispatch.

Each rule is independently testable. The tests pin both the positive
(drift seen → event emitted with correct reason/severity) and negative
(drift absent → None returned) paths so a future tweak that loosens
detection can't accidentally start flooding audit_log with false
positives.

Also pins the rule-registry contract: adding new rules later
(``wrong_tool_selected``, ``multi_tool_only_cited_one`` for the
agentic toggle) is just appending to ``DRIFT_RULES``. The dispatcher
behavior — ignore exceptions, write one audit row per event, respect
the ``assistant.drift_detection_enabled`` setting — stays unchanged.
"""
from unittest.mock import patch

import pytest

from app.services.assistant import drift
from app.services.assistant.drift import (
    DriftContext, DriftEvent,
    _empty_response, _invented_citation, _missing_citation,
    _refused_with_context,
    detect_and_log,
)


def _ctx(*, response: str = "answer", retrieval_count: int = 0,
          flow: str = "legacy", handler: str = "faq",
          intent: str | None = "FAQ", question: str = "q") -> DriftContext:
    """Default-arg helper so tests stay focused on the variable they're
    actually exercising."""
    return DriftContext(
        user_id=1, flow=flow, handler=handler, intent=intent,
        question=question, response=response,
        retrieval_count=retrieval_count,
    )


# ============================================================ refused_with_context

@pytest.mark.parametrize("phrase", [
    "outside the scope",
    "outside of the scope",
    "outside my scope",
    "I'm unable to provide",
    "I am unable to provide",
    "I cannot help with",
    "I can't help with",
    "I don't have information",
    "I do not have information",
    "I don't have access",
    "I do not have access",
])
def test_refused_with_context_fires_for_each_known_phrase(phrase):
    """REGRESSION GUARD: each phrase in _REFUSAL_PHRASES must trigger
    the rule when chunks were available. If a tweak removes one,
    operators stop seeing that class of refusal in the dashboard."""
    ev = _refused_with_context(_ctx(
        response=f"I think {phrase} of CPMAI-related topics.",
        retrieval_count=3,
    ))
    assert ev is not None
    assert ev.reason == "refused_with_context"
    assert phrase.lower() in ev.detail.lower()


def test_refused_with_context_skips_when_no_chunks_retrieved():
    """If retrieval was empty, a refusal is the CORRECT answer
    ("I don't know about this; I have no sources"). Don't flag."""
    ev = _refused_with_context(_ctx(
        response="That's outside the scope of what I can answer.",
        retrieval_count=0,
    ))
    assert ev is None


def test_refused_with_context_skips_when_response_is_normal():
    """Sanity: a normal answer doesn't trigger the rule."""
    ev = _refused_with_context(_ctx(
        response="CPMAI Phase 3 covers data engineering activities.",
        retrieval_count=3,
    ))
    assert ev is None


# ============================================================ empty_response

def test_empty_response_fires_on_short_text():
    """LLM returned essentially nothing → the user sees a broken UX.
    Flag at error-severity so it stands out on the dashboard."""
    ev = _empty_response(_ctx(response="ok"))
    assert ev is not None
    assert ev.reason == "empty_response"
    assert ev.severity == "error"


def test_empty_response_skips_normal_answer():
    ev = _empty_response(_ctx(
        response="A normal-length answer that is longer than 20 chars."))
    assert ev is None


# ============================================================ missing_citation

def test_missing_citation_fires_when_chunks_retrieved_but_uncited():
    """Retrieval found chunks, system prompt asked for citations, LLM
    didn't cite. The user sees an answer with no provenance."""
    ev = _missing_citation(_ctx(
        response="The answer is twenty-six.",
        retrieval_count=3,
    ))
    assert ev is not None
    assert ev.reason == "missing_citation"


def test_missing_citation_skips_when_no_chunks_retrieved():
    """Nothing to cite, no rule violation."""
    ev = _missing_citation(_ctx(
        response="A bare-LLM answer with no sources.",
        retrieval_count=0,
    ))
    assert ev is None


def test_missing_citation_skips_when_response_cites_correctly():
    ev = _missing_citation(_ctx(
        response="Per [Source 1] the answer is ...",
        retrieval_count=3,
    ))
    assert ev is None


# ============================================================ invented_citation

def test_invented_citation_fires_for_out_of_range_source_number():
    """LLM cited [Source 7] but only 3 chunks were provided. User
    clicks the chip expecting a 7th source and finds nothing."""
    ev = _invented_citation(_ctx(
        response="Per [Source 7] this is correct.",
        retrieval_count=3,
    ))
    assert ev is not None
    assert ev.reason == "invented_citation"
    assert ev.severity == "error"
    assert "7" in ev.detail


def test_invented_citation_fires_for_zero_or_negative_source():
    """[Source 0] is also invented (we 1-index). Pin both the high
    end AND the low end of the invalid range."""
    ev = _invented_citation(_ctx(
        response="Per [Source 0] this is true.",
        retrieval_count=3,
    ))
    assert ev is not None


def test_invented_citation_skips_for_valid_in_range_citations():
    """[Source 1], [Source 2], [Source 3] are all valid when 3 chunks
    were retrieved. Don't flag."""
    ev = _invented_citation(_ctx(
        response="Per [Source 1] and [Source 3] the answer is ...",
        retrieval_count=3,
    ))
    assert ev is None


# ============================================================ dispatcher

def test_detect_and_log_runs_no_rules_when_disabled():
    """Default state (assistant.drift_detection_enabled=false) — no
    rules run, no audit rows written. Operator opt-in only."""
    with patch.object(drift, "_enabled", return_value=False):
        events = detect_and_log(db=None, ctx=_ctx(
            response="hi", retrieval_count=5))
    assert events == []


def test_detect_and_log_writes_one_audit_row_per_event():
    """Multiple drift events for the same turn → one audit_log write
    per event, each with its specific reason."""
    written: list[tuple[str, dict]] = []

    def fake_audit_log(_db, _user_id, action, metadata):
        written.append((action, metadata))

    with patch.object(drift, "_enabled", return_value=True), \
         patch.object(drift, "audit_log", side_effect=fake_audit_log):
        # This response triggers BOTH refused_with_context AND
        # missing_citation: it refuses but we had chunks to cite.
        ctx = _ctx(
            response="That's outside the scope, sorry.",
            retrieval_count=4,
        )
        events = detect_and_log(db=None, ctx=ctx)

    assert len(events) >= 2
    actions = [a for a, _ in written]
    assert "assistant.drift.refused_with_context" in actions
    assert "assistant.drift.missing_citation" in actions


def test_detect_and_log_includes_flow_in_metadata():
    """REGRESSION GUARD for the legacy-vs-agentic comparison feature.
    Every audit row carries the ``flow`` discriminator so the dashboard
    can group by it. If a future refactor drops this field, the
    side-by-side comparison breaks silently."""
    captured_meta: list[dict] = []

    def fake_audit_log(_db, _user_id, _action, metadata):
        captured_meta.append(metadata)

    with patch.object(drift, "_enabled", return_value=True), \
         patch.object(drift, "audit_log", side_effect=fake_audit_log):
        detect_and_log(db=None, ctx=_ctx(
            response="ok", retrieval_count=0, flow="legacy"))

    # _empty_response fires (response < 20 chars) → one row written.
    assert len(captured_meta) == 1
    meta = captured_meta[0]
    assert meta["flow"] == "legacy"
    # Dashboard groupers also need handler + reason + retrieval_chunks_count.
    assert meta["handler"] == "faq"
    assert meta["drift_reason"] == "empty_response"
    assert meta["retrieval_chunks_count"] == 0


def test_detect_and_log_swallows_rule_exceptions():
    """A misbehaving rule must not take down the chat turn. Exceptions
    inside a rule are caught + the rule's verdict is dropped; other
    rules still run."""
    def crashing_rule(_ctx):
        raise RuntimeError("boom")

    with patch.object(drift, "_enabled", return_value=True), \
         patch.object(drift, "DRIFT_RULES",
                       [crashing_rule, _empty_response]), \
         patch.object(drift, "audit_log"):
        events = detect_and_log(db=None, ctx=_ctx(response="x"))
    # crashing_rule was eaten; _empty_response still ran and fired
    # (response is 1 char, well under the 20-char threshold).
    assert len(events) == 1
    assert events[0].reason == "empty_response"


def test_detect_and_log_swallows_audit_log_exceptions():
    """Even if the audit-log write itself throws (DB outage, etc.),
    detection doesn't take down the chat. The events list still comes
    back so callers can act on it if they want; only the persistence
    failed."""
    def crashing_audit(*_args, **_kw):
        raise RuntimeError("audit table locked")

    with patch.object(drift, "_enabled", return_value=True), \
         patch.object(drift, "audit_log", side_effect=crashing_audit):
        events = detect_and_log(db=None, ctx=_ctx(response="x"))
    assert len(events) == 1   # _empty_response still fired
