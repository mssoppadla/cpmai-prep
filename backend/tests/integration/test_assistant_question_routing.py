"""Question-routing eval matrix — regression guard for "the right
handler answers the right question and pulls from the right sources."

Each question is a frozen test case representing a real-world phrasing
the operator wants the assistant to handle correctly. Each carries:

  * ``expected_intent``               — which Intent the legacy
                                        regex classifier should pick
  * ``expected_legacy_sources``       — which RAG source_types the
                                        chosen handler queries
  * ``expected_legacy_citation_types``— which source_types ALL must
                                        appear in the response's
                                        citations (when the seeded
                                        chunk for that type is the
                                        most-relevant retrieval match)
  * ``expected_agentic_tools``        — (FUTURE) which tools the
                                        agentic LLM should pick once
                                        the toggle ships. Stored on
                                        the dataclass now so the same
                                        matrix powers both assertion
                                        paths — when agentic ships
                                        we just flip the runner.

This test file is also the LIVING SPEC of "what kinds of questions
should go where." Adding a new entry is one tuple in QUESTIONS;
removing one means an explicit decision about which routing case
no longer needs guarding.

Today only the legacy assertions run — the agentic_tools field is a
placeholder until the agentic toggle ships. When it does, an
``if agentic_enabled`` branch in the runner asserts those instead.
"""
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from app.services.assistant.handlers.account_handler import AccountHandler
from app.services.assistant.handlers.content_handler import ContentHandler
from app.services.assistant.handlers.faq_handler import FAQHandler
from app.services.assistant.handlers.insights_handler import InsightsHandler
from app.services.assistant.handlers.pmi_handler import PmiReferenceHandler
from app.services.assistant.intent_classifier import Intent, IntentClassifier
from app.services.assistant.rag.handler_support import SHARED_KNOWLEDGE_SOURCES

# The cross-cutting site-knowledge pool (uploads + CMS pages + course
# catalog + live-session schedule). FAQ/Content handlers spread this
# into their filters, so the expected sets derive from the constant —
# extending the pool must not silently drop a handler's primary source.
_SHARED = set(SHARED_KNOWLEDGE_SOURCES)


@dataclass
class QuestionCase:
    """One frozen question + the routing/retrieval it should produce.

    Naming/structure designed for both today's classifier-routed
    legacy path AND the future agentic tool-calling path. Today only
    the first two fields are asserted; the agentic_tools field is
    pre-populated so the matrix doesn't need rewriting later."""
    question: str
    expected_intent: Intent
    expected_legacy_sources: set[str]
    expected_agentic_tools: set[str] = field(default_factory=set)
    notes: str = ""


# Map Intent → handler class so the runner can build the right handler
# when verifying which sources it queries.
_INTENT_TO_HANDLER = {
    Intent.ACCOUNT:        AccountHandler,
    Intent.FAQ:            FAQHandler,
    Intent.CONTENT:        ContentHandler,
    Intent.INSIGHTS:       InsightsHandler,
    Intent.PMI_REFERENCE:  PmiReferenceHandler,
}


# ============================================================ THE MATRIX

QUESTIONS: list[QuestionCase] = [
    # ---- FAQ-style questions: certification process / exam logistics
    QuestionCase(
        question="What's the eligibility for the CPMAI exam?",
        expected_intent=Intent.FAQ,
        expected_legacy_sources={"faq"} | _SHARED,
        expected_agentic_tools={"faq", "upload"},
    ),
    QuestionCase(
        question="How long is the exam? What's the passing score?",
        expected_intent=Intent.FAQ,
        expected_legacy_sources={"faq"} | _SHARED,
        expected_agentic_tools={"faq", "upload"},
    ),

    # ---- CONTENT: explanatory questions about CPMAI methodology
    QuestionCase(
        question="Explain CPMAI Phase 3 and what it covers",
        expected_intent=Intent.CONTENT,
        expected_legacy_sources={"question_explanation"} | _SHARED,
        expected_agentic_tools={"content", "upload"},
        notes="'phase' keyword routes to CONTENT",
    ),
    QuestionCase(
        question="What is the deployment phase about?",
        expected_intent=Intent.CONTENT,
        expected_legacy_sources={"question_explanation"} | _SHARED,
        expected_agentic_tools={"content", "upload"},
        notes="'what is' + 'deployment' keywords route to CONTENT",
    ),

    # ---- ACCOUNT: subscription / pricing questions
    QuestionCase(
        question="How much does the Premium subscription cost?",
        expected_intent=Intent.ACCOUNT,
        expected_legacy_sources={"plan", "course"},
        expected_agentic_tools={"account"},
    ),
    QuestionCase(
        question="Can I get a refund if I cancel my plan?",
        expected_intent=Intent.ACCOUNT,
        expected_legacy_sources={"plan", "course"},
        expected_agentic_tools={"account"},
    ),

    # ---- PMI_REFERENCE: link-out to PMI's official page
    QuestionCase(
        question="Where do I register for the actual exam?",
        expected_intent=Intent.PMI_REFERENCE,
        expected_legacy_sources=set(),   # no RAG — deterministic URL handler
        expected_agentic_tools={"pmi"},
        notes="'register' + 'exam' keywords trigger PMI link-out",
    ),

    # ---- INSIGHTS: personal exam attempt analysis
    QuestionCase(
        question="How did I do on my last exam?",
        expected_intent=Intent.INSIGHTS,
        expected_legacy_sources=set(),   # no RAG — DB query of user's attempts
        expected_agentic_tools={"insights"},
    ),

    # ---- DEFAULT FALLTHROUGH: questions the regex doesn't recognise
    # default to CONTENT (not FAQ — see classifier.classify docstring
    # for the full rationale; short version: ContentHandler has the
    # broader DEFAULT_SYSTEM and is the surface operators customise,
    # so it's the better catch-all for off-keyword questions).
    QuestionCase(
        question="What are GDPR Rules?",
        expected_intent=Intent.CONTENT,       # default fallthrough is now CONTENT
        expected_legacy_sources={"question_explanation"} | _SHARED,
        expected_agentic_tools={"content", "upload"},
        notes="REGRESSION (operator-reported, May 2026): GDPR fell "
              "through to FAQ default; FAQHandler's narrow self-image "
              "('CPMAI certification process') made the LLM refuse "
              "even with retrieved context AND an explicit ALSO ALLOWED "
              "preamble entry. Fix: default fallthrough is CONTENT, "
              "which has a broader prompt and is the operator-customised "
              "handler. Pin both the routing change AND the source "
              "filter so neither can silently regress.",
    ),
    QuestionCase(
        question="Tell me about machine learning model evaluation",
        expected_intent=Intent.CONTENT,       # default fallthrough is now CONTENT
        expected_legacy_sources={"question_explanation"} | _SHARED,
        expected_agentic_tools={"content", "upload"},
        notes="ML/AI topic falls through to CONTENT default; the broader "
              "system prompt + upload corpus together let the LLM answer "
              "without refusing.",
    ),
    # ---- SITE-WIDE KNOWLEDGE (July 2026): live classes + course catalog
    QuestionCase(
        question="When is the next live class?",
        expected_intent=Intent.FAQ,
        expected_legacy_sources={"faq"} | _SHARED,
        expected_agentic_tools={"live_sessions"},
        notes="'live class' keyword routes to FAQ; the shared pool "
              "includes the zoom_session corpus, so the schedule (with "
              "dates) is retrievable. Agentic flow uses the live-DB "
              "live_sessions tool instead.",
    ),
    QuestionCase(
        question="What courses do you offer on this platform?",
        expected_intent=Intent.ACCOUNT,
        expected_legacy_sources={"plan", "course"},
        expected_agentic_tools={"account"},
        notes="'offer' is an ACCOUNT keyword — and that's fine now: "
              "AccountHandler retrieves plan AND course corpora, so a "
              "catalog question landing there still gets real course "
              "titles + prices.",
    ),
    QuestionCase(
        question="Which courses are available for CPMAI preparation?",
        expected_intent=Intent.CONTENT,
        expected_legacy_sources={"question_explanation"} | _SHARED,
        expected_agentic_tools={"content", "upload"},
        notes="No keyword match falls through to CONTENT; the shared "
              "pool includes the course catalog so the handler can "
              "answer with real titles/prices.",
    ),
]


# ============================================================ runner

@pytest.fixture
def classifier():
    return IntentClassifier()


@pytest.mark.parametrize("case", QUESTIONS,
                          ids=[c.question[:50] for c in QUESTIONS])
def test_legacy_routing(case: QuestionCase, classifier):
    """Single parametrised test that, for each frozen question,
    asserts:

      1. The regex classifier picks the expected_intent.
      2. The handler that intent maps to queries
         ``expected_legacy_sources`` from RAG.

    For PMI_REFERENCE + INSIGHTS the source set is empty (those
    handlers don't do RAG retrieval); we assert the handler doesn't
    invoke retrieve_context at all in those cases.

    When the agentic toggle ships, add a second parametrised test
    `test_agentic_routing` that flips the toggle and asserts
    ``expected_agentic_tools`` instead. The matrix doesn't change.
    """
    # 1. Classifier intent.
    intent, _confidence = classifier.classify(case.question, [])
    assert intent == case.expected_intent, (
        f"Question {case.question!r} routed to {intent}, "
        f"expected {case.expected_intent}. {case.notes}")

    # 2. Handler retrieval source_types.
    handler_cls = _INTENT_TO_HANDLER[case.expected_intent]
    handler = _build_handler_for_assertion(handler_cls)

    if not case.expected_legacy_sources:
        # PMI / INSIGHTS handlers don't do RAG — they don't even import
        # retrieve_context. The mere absence of that import IS the
        # no-RAG contract. Pin it via a hasattr check rather than
        # patching (you can't patch what isn't there).
        import importlib
        mod = importlib.import_module(handler_cls.__module__)
        assert not hasattr(mod, "retrieve_context"), (
            f"{handler_cls.__name__}'s module imports retrieve_context "
            f"but expected_legacy_sources is empty for {case.question!r}. "
            "Either remove the import or add expected sources.")
        return

    captured: dict = {}
    def fake_retrieve(_db, _query, *, source_types=None, k=None):
        captured["source_types"] = set(source_types) if source_types else set()
        return []

    with patch_handler_retrieve(handler_cls, fake_retrieve):
        handler.respond(_fake_request(case.question), user=None)

    assert captured["source_types"] == case.expected_legacy_sources, (
        f"Question {case.question!r} → {handler_cls.__name__} queried "
        f"{captured['source_types']}, expected {case.expected_legacy_sources}. "
        f"{case.notes}")


# ============================================================ helpers

def _build_handler_for_assertion(handler_cls):
    """Construct a handler with mocked DB + a no-op LLM provider.
    The provider's complete() returns a canned string so the handler
    runs end-to-end without hitting OpenAI."""
    db = MagicMock()
    provider = MagicMock()
    provider.complete.return_value = "ok"
    return handler_cls(db, provider)


def _fake_request(question: str):
    request = MagicMock()
    request.message = question
    request.history = []
    return request


def patch_handler_retrieve(handler_cls, side_effect=None):
    """Patch the retrieve_context import in the handler's module.
    Each handler imports it from rag.handler_support, but Python
    binds the import into the handler's namespace at module-load
    time — so we need to patch it where the handler reads it from,
    not where it's defined."""
    module_name = handler_cls.__module__
    if side_effect is None:
        # When the test doesn't care about retrieve's behavior (only
        # whether it's called), return [] so the handler proceeds.
        side_effect = lambda *_a, **_kw: []   # noqa: E731
    return patch(f"{module_name}.retrieve_context", side_effect=side_effect)
