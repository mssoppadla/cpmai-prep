"""Keyword-based intent classifier — admin-tunable at runtime.

LLM-based classification is a planned upgrade (lives in the agentic
flow's router today; this module is the legacy path). Keyword-first
works well enough because users tend to phrase questions with strong
vocabulary tells ("how much" → ACCOUNT, "explain" → CONTENT,
"pmi.org" → PMI_REFERENCE).

**Admin-tunable.** Per-intent keyword lists are now read from
``settings_store`` at classify time, so an operator can add or remove
substrings without a redeploy. Why this matters: when the FAQ corpus
adds a new topic (e.g. "How much does CPMAI cost?"), the operator
needs to be able to route that question to the right handler without
shipping a code change. The agentic flow solves this with a real LLM
router, but the legacy flow still ships as the seed default — we keep
it tunable for operators who prefer the predictability of a keyword
classifier or who haven't flipped to agentic yet.

Intent ordering matters: most specific routes first. PMI_REFERENCE
above FAQ because "where do I register for the exam" matches both
patterns but the PMI link-out is the more useful response. The order
itself stays hardcoded (V1) — admin tunes keywords within the
existing priority structure.

Defaults: the hardcoded ``_DEFAULT_KEYWORDS`` map below is the seed
content for the 5 new settings. The classifier falls back to these
when a setting row is missing (fresh install pre-seed). When a
setting row exists with an empty list, that intent has NO keyword
matches — admin's explicit choice.

Default fallthrough (when no keyword matches) is admin-configurable
via ``assistant.classifier.default_intent`` (existing setting,
unchanged). Defaults to "content".
"""
from __future__ import annotations

import structlog
from enum import Enum

from app.core.settings_store import settings_store

# Structlog (not stdlib logging) so kw-args land in structured output —
# the same pattern the orchestrator + drift detector use.
log = structlog.get_logger("assistant.intent_classifier")


class Intent(str, Enum):
    ACCOUNT        = "account"
    FAQ            = "faq"
    CONTENT        = "content"
    INSIGHTS       = "insights"
    PMI_REFERENCE  = "pmi_reference"


# Hardcoded fallback for each intent. These are also the seed values
# written to ``seeds/default_settings.json``, so on a fresh install
# the DB and this map agree. The classifier reads from settings_store
# at classify time; this map only fires as a fallback when the
# setting row is missing entirely.
_DEFAULT_KEYWORDS: dict[Intent, list[str]] = {
    Intent.PMI_REFERENCE: [
        "pmi.org", "pmi website", "register for the exam",
        "register for exam", "exam content outline", "eco link", "eco",
        "course bundle link", "where do i register", "where to register",
        "exam fee", "exam cost", "official exam", "syllabus",
        "what's on the exam", "what is on the exam",
    ],
    Intent.INSIGHTS: [
        "my score", "my exam", "weak area", "my progress",
        "how did i", "improve", "my attempt",
    ],
    Intent.ACCOUNT: [
        "subscription", "billing", "payment", "signup",
        "plan", "invoice", "refund", "cancel", "price", "pricing",
        "discount", "offer", "coupon",
    ],
    Intent.CONTENT: [
        "explain", "what is", "define", "phase", "cpmai phase",
        "topic", "concept", "domain", "business understanding",
        "data understanding", "modeling", "deployment",
    ],
    Intent.FAQ: [
        "exam pattern", "passing", "duration", "fee", "eligibility",
        "certification", "how do i take", "schedule", "format",
        "exam date", "exam time",
    ],
}


# Priority order — first match wins. Hardcoded because changing it at
# runtime would let an operator accidentally invert the routing for
# overlapping keywords (e.g. ACCOUNT first, "exam cost" lands on
# ACCOUNT instead of PMI_REFERENCE). Tunable in code, not in settings.
_INTENT_ORDER: list[Intent] = [
    Intent.PMI_REFERENCE,
    Intent.INSIGHTS,
    Intent.ACCOUNT,
    Intent.CONTENT,
    Intent.FAQ,
]


# Confidence values surfaced on the response. 0.85 for a positive
# keyword match (high-confidence routing); 0.4 for the default
# fallthrough (low-confidence — we don't actually know what the user
# wanted, we just have a fallback handler). The drift dashboard
# correlates low-confidence rows with poor answers; if you see a lot
# of 0.4-confidence drifts, that's a signal to add keywords for the
# topics that aren't matching.
_CONF_MATCH    = 0.85
_CONF_FALLBACK = 0.4


def _resolve_keywords_for(intent: Intent) -> list[str]:
    """Read admin-tunable keywords for an intent from settings_store.

    Three cases the resolver handles:

      * Setting row exists and is a non-empty list → use it (lowercased
        + stripped); admin's edit takes effect on the next chat turn
        (after the 30s settings cache TTL, or instantly via the
        Redis invalidation pubsub).

      * Setting row exists but is empty list ``[]`` → admin's explicit
        "this intent never matches via keyword" choice. Returns []
        and classify() moves to the next intent.

      * Setting row missing OR malformed (not a list, contains
        non-strings, etc.) → fall back to the hardcoded default. Logs
        a warning so operators can see in structured logs what
        happened.
    """
    key = f"assistant.classifier.keywords.{intent.value}"
    value = settings_store.get(key)

    if value is None:
        # Fresh install pre-seed, or settings_store error. Hardcoded
        # default is always a safe fallback.
        return _DEFAULT_KEYWORDS[intent]

    if not isinstance(value, list):
        log.warning("classifier.keywords_not_a_list",
                     intent=intent.value, type=type(value).__name__)
        return _DEFAULT_KEYWORDS[intent]

    # Lowercase + strip at read time (not at write time) so the admin
    # form preserves the case they typed. The classifier matches on
    # the lowercased message anyway, so case-folded at read makes the
    # match behave intuitively whatever the admin saved.
    cleaned: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            continue
        s = entry.strip().lower()
        if s:
            cleaned.append(s)
    return cleaned


class IntentClassifier:
    """Keyword classifier. ``classify(message)`` returns
    (Intent, confidence).

    The keyword sets per intent are read from ``settings_store`` per
    call — admin edits propagate within the standard 30s cache TTL.
    The settings_store reads are Redis-cached and very fast; doing 5
    reads per classify call is fine (typical chat turn is ~1-3 seconds
    end-to-end, dominated by LLM time).
    """

    def classify(self, message: str, history: list | None = None
                 ) -> tuple[Intent, float]:
        m = message.lower()
        for intent in _INTENT_ORDER:
            for kw in _resolve_keywords_for(intent):
                if kw in m:
                    return intent, _CONF_MATCH
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
        return _resolve_default_intent(), _CONF_FALLBACK


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
