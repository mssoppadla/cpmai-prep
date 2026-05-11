"""Content handler — explains CPMAI concepts grounded in question-bank
explanations.

Retrieves the top-k matching question-explanation chunks via RAG. These
are the per-question "why this is the right answer" notes admins author
in the Question editor — they're our richest source of CPMAI-specific
explanatory text.
"""
from app.services.assistant.providers.base import LLMProvider
from app.services.assistant.rag.handler_support import (
    build_context_block, retrieve_context, to_citations,
)
from app.services.assistant.system_prompt import with_preamble


SYSTEM = (
    "You explain CPMAI concepts (the 6-phase methodology) clearly and "
    "concisely. Use plain language; analogies are welcome. Prefer the "
    "provided source material over your prior knowledge — if a source "
    "conflicts with what you'd say from memory, trust the source."
)


class ContentHandler:
    def __init__(self, db, provider: LLMProvider):
        self.db = db; self.provider = provider

    def respond(self, request, user) -> dict:
        chunks = retrieve_context(
            self.db, request.message,
            source_types=["question_explanation"])
        context = build_context_block(chunks)
        base = (SYSTEM + "\n\n" + context) if context else SYSTEM
        system = with_preamble(base)
        history = [{"role": m.role, "content": m.content} for m in request.history]
        history.append({"role": "user", "content": request.message})
        text = self.provider.complete(system, history)
        return {"message": text,
                "citations": to_citations(chunks),
                "suggested_actions": []}
