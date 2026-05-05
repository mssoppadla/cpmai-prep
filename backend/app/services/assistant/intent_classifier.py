"""Keyword-based intent classifier with LLM fallback hook."""
from enum import Enum


class Intent(str, Enum):
    ACCOUNT  = "account"
    FAQ      = "faq"
    CONTENT  = "content"
    INSIGHTS = "insights"


class IntentClassifier:
    KEYWORDS = {
        Intent.ACCOUNT:  ["subscription", "billing", "payment", "register", "signup",
                          "plan", "invoice", "refund", "cancel"],
        Intent.INSIGHTS: ["my score", "my exam", "weak area", "my progress",
                          "how did i", "improve", "my attempt"],
        Intent.CONTENT:  ["explain", "what is", "define", "phase", "cpmai phase",
                          "topic", "concept"],
        Intent.FAQ:      ["exam pattern", "passing", "duration", "fee", "eligibility",
                          "certification", "how do i take", "schedule"],
    }

    def classify(self, message: str, history: list | None = None
                 ) -> tuple[Intent, float]:
        m = message.lower()
        for intent, kws in self.KEYWORDS.items():
            for kw in kws:
                if kw in m:
                    return intent, 0.85
        return Intent.FAQ, 0.5
