"""FAQ handler — grounds responses in the CPMAI FAQ corpus.

Retrieves the top-k matching FAQ entries via RAG, prepends them to the
system prompt, asks the LLM to answer + cite. Falls through to a
bare-LLM answer if RAG is empty (mid-rollout / OpenAI hiccup) — the
chat stays useful instead of failing closed.
"""
from app.services.assistant.providers.base import LLMProvider
from app.services.assistant.rag.handler_support import (
    build_context_block, retrieve_context, to_citations,
)


SYSTEM = (
    "You answer factual questions about the CPMAI certification process — "
    "eligibility, exam format, scoring, scheduling. Be concise and accurate. "
    "If the provided sources don't cover the question, say you don't know "
    "rather than guess."
)


class FAQHandler:
    def __init__(self, db, provider: LLMProvider):
        self.db = db; self.provider = provider

    def respond(self, request, user) -> dict:
        chunks = retrieve_context(self.db, request.message, source_types=["faq"])
        context = build_context_block(chunks)
        system = (SYSTEM + "\n\n" + context) if context else SYSTEM
        history = [{"role": m.role, "content": m.content} for m in request.history]
        history.append({"role": "user", "content": request.message})
        text = self.provider.complete(system, history)
        return {"message": text,
                "citations": to_citations(chunks),
                "suggested_actions": []}
