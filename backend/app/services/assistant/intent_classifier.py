"""Keyword-based intent classifier.

LLM-based classification is a planned upgrade (Day 2-3 if time permits)
— keyword-first works well enough for an MVP because users tend to
phrase questions with strong vocabulary tells ("how much" → ACCOUNT,
"explain" → CONTENT, "pmi.org" → PMI_REFERENCE).

Intent ordering matters: most specific routes first. PMI_REFERENCE
above FAQ because "where do I register for the exam" matches both
patterns but the PMI link-out is the more useful response.
"""
from enum import Enum


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
        return Intent.FAQ, 0.5
