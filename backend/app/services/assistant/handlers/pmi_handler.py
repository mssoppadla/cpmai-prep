"""PMI reference handler — pure config lookup, no LLM call.

When the user asks "where do I register for the actual CPMAI exam?"
or "what's on the exam?", the right answer is a link to PMI's official
page — not paraphrased text that could drift from PMI's source of
truth. This handler returns the configured URL + a one-line frame.

URLs are admin-configurable via Runtime Settings (`pmi.course_bundle_url`,
`pmi.eco_url`), so updating them when PMI moves a page is a one-click
operation, no deploy needed.

Why not let an LLM say "here, look at pmi.org/cpmai": prompt-engineering
LLMs to *always* reach for the right link is unreliable. A deterministic
handler is cheaper, faster, and guaranteed-correct.
"""
from app.core.settings_store import settings_store
from app.services.assistant.providers.base import LLMProvider


class PmiReferenceHandler:
    """No LLM dependency — returns a deterministic response built from
    config. The `provider` arg is accepted for handler-API uniformity
    but not used."""

    def __init__(self, db, provider: LLMProvider):
        self.db = db
        # Kept for interface compatibility with the other handlers;
        # PMI link-out is a pure lookup, no completion needed.
        self.provider = provider

    def respond(self, request, user) -> dict:
        msg_lower = request.message.lower()

        # Decide which URL to surface based on which keyword triggered
        # the routing. ECO/exam-content takes precedence when both
        # match (more specific intent).
        eco_keywords     = ("eco", "exam content", "outline", "syllabus",
                              "what's on the exam", "what is on the exam",
                              "topics covered")
        course_keywords  = ("register", "enroll", "sign up for exam",
                              "exam fee", "exam cost", "course bundle",
                              "pmi.org", "pmi website")

        course_url = settings_store.get_str("pmi.course_bundle_url", "")
        eco_url    = settings_store.get_str("pmi.eco_url", "")

        if any(k in msg_lower for k in eco_keywords) and eco_url:
            return self._link_response(
                eco_url,
                title="Official CPMAI Exam Content Outline",
                body=("PMI publishes the canonical Exam Content Outline "
                       "(ECO) for the CPMAI certification — every domain, "
                       "task, and enabler the exam can test against. "
                       "It's the single source of truth for what's "
                       "covered. Open it directly here:"),
            )

        if any(k in msg_lower for k in course_keywords) and course_url:
            return self._link_response(
                course_url,
                title="CPMAI Course Bundle on PMI",
                body=("CPMAI registration and the official course bundle "
                       "are managed by PMI directly. You'll find pricing, "
                       "registration steps, and exam scheduling on their "
                       "page:"),
            )

        # No relevant URL configured OR the message didn't actually match
        # — fall through to a generic pointer.
        return {
            "message": (
                "The CPMAI exam and its official course materials are "
                "managed by PMI directly at https://www.pmi.org. Our admin "
                "hasn't yet configured a direct link from here — please "
                "search 'CPMAI' on pmi.org for the latest registration "
                "page."
            ),
            "citations": [],
            "suggested_actions": [],
        }

    @staticmethod
    def _link_response(url: str, *, title: str, body: str) -> dict:
        return {
            "message": f"{body}\n\n{url}",
            "citations": [{"source": "PMI", "title": title, "url": url}],
            "suggested_actions": [{"label": title, "url": url}],
        }
