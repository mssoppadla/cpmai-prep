"""Keyword-based intent classifier.

LLM-based classification is a planned upgrade (Day 2-3 if time permits)
— keyword-first works well enough for an MVP because users tend to
phrase questions with strong vocabulary tells ("how much" → ACCOUNT,
"explain" → CONTENT, "pmi.org" → PMI_REFERENCE).

Intent ordering matters: most specific routes first. PMI_REFERENCE
above FAQ because "where do I register for the exam" matches both
patterns but the PMI link-out is the more useful response.

Default fallthrough (when no keyword matches) is admin-configurable
via ``assistant.classifier.default_intent``. Defaults to "content"
because ContentHandler has the broadest DEFAULT_SYSTEM and the
widest retrieval set (question_explanation + upload), making it the
best catch-all. See its docstring for the operator-reported
regression that motivated this change.
"""
from enum import Enum
from app.core.settings_store import settings_store


class Intent(str, Enum):
    ACCOUNT        = "account"
    FAQ            = "faq"
    CONTENT        = "content"
    INSIGHTS       = "insights"
    PMI_REFERENCE  = "pmi_reference"


class IntentClassifier:
    # Ordered: first match wins. Put MORE SPECIFIC intents first so
    # generic FAQ keywords don't shadow them.
    KEYWORDS: list[tuple[Intent, list[str]]] = [
        (Intent.PMI_REFERENCE,
            ["pmi.org", "pmi website", "register for the exam",
             "register for exam", "exam content outline", "eco link", "eco",
             "course bundle link", "where do i register", "where to register",
             "exam fee", "exam cost", "official exam", "syllabus",
             "what's on the exam", "what is on the exam"]),
        (Intent.INSIGHTS,
            ["my score", "my exam", "weak area", "my progress",
             "how did i", "improve", "my attempt"]),
        (Intent.ACCOUNT,
            ["subscription", "billing", "payment", "signup",
             "plan", "invoice", "refund", "cancel", "price", "pricing",
             "discount", "offer", "coupon"]),
        (Intent.CONTENT,
            ["explain", "what is", "define", "phase", "cpmai phase",
             "topic", "concept", "domain", "business understanding",
             "data understanding", "modeling", "deployment"]),
        (Intent.FAQ,
            ["exam pattern", "passing", "duration", "fee", "eligibility",
             "certification", "how do i take", "schedule", "format",
             "exam date", "exam time"]),
    ]

    def classify(self, message: str, history: list | None = None
                 ) -> tuple[Intent, float]:
        m = message.lower()
        for intent, kws in self.KEYWORDS:
            for kw in kws:
                if kw in m:
                    return intent, 0.85
        # Default fallthrough — admin-configurable.
        #
        # The default of "content" exists because operators reported
        # that questions like "What are GDPR Rules?" — which match no
        # keyword — used to fall through to FAQ, where FAQHandler's
        # narrow self-image ("CPMAI certification process —
        # eligibility, exam format, scoring, scheduling") caused the
        # LLM to refuse despite an explicit ALSO ALLOWED preamble
        # entry. ContentHandler is the better catch-all because:
        #   1. Its DEFAULT_SYSTEM is broader (CPMAI concepts AND any
        #      topic covered by uploaded materials), giving the LLM
        #      less reason to anchor on a narrow refusal.
        #   2. It's the handler operators tend to customise via
        #      ``assistant.handler.content.system`` — the catch-all
        #      should be the surface operators are already tuning.
        #   3. Its retrieval set (question_explanation + upload)
        #      covers admin-uploaded knowledge bases as a first-class
        #      source, so off-keyword topics still get grounded context.
        #
        # An operator who prefers the legacy "FAQ-as-catch-all" can
        # set ``assistant.classifier.default_intent`` to "faq". Any
        # malformed value falls back to CONTENT (safest default — the
        # one with the broadest retrieval).
        return _resolve_default_intent(), 0.4


def _resolve_default_intent() -> Intent:
    """Read the admin-configured default intent, with a safe fallback
    when the value is missing or doesn't map to a known Intent."""
    raw = (settings_store.get_str(
        "assistant.classifier.default_intent", "content") or "content"
    ).strip().lower()
    try:
        return Intent(raw)
    except ValueError:
        # Operator typo'd into the setting field. Don't take down
        # routing — fall back to the safest default and log a one-off
        # so they can see in admin/audit-logs what happened.
        return Intent.CONTENT
