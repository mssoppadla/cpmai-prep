"""Content handler — explains CPMAI concepts grounded in question-bank
explanations + admin-uploaded reference documents.

Retrieves the top-k matching chunks via RAG from two sources:

  * ``question_explanation`` — per-question "why this is the right
    answer" notes admins author in the Question editor; the richest
    source of CPMAI-specific explanatory text.
  * ``upload`` (and any future SHARED_KNOWLEDGE_SOURCES) — admin-
    uploaded reference docs (knowledge bases, study guides, supporting
    materials). Folded in here so an upload-only topic the question
    bank doesn't cover (e.g. GDPR, EU AI Act) can still be answered
    from the LLM with grounded context.
"""
from app.services.assistant.providers.base import LLMProvider
from app.services.assistant.rag.handler_support import (
    SHARED_KNOWLEDGE_SOURCES,
    build_context_block, retrieve_context, to_citations,
)
from app.services.assistant.system_prompt import (
    configurable_handler_system, with_preamble,
)


# Hardcoded fallback — used when assistant.handler.content.system is empty.
DEFAULT_SYSTEM = (
    "You explain CPMAI concepts (the 6-phase methodology) AND any topic "
    "covered by the admin-uploaded reference materials in the provided "
    "sources. Use plain language; analogies are welcome. Prefer the "
    "provided source material over your prior knowledge — if a source "
    "conflicts with what you'd say from memory, trust the source. If "
    "the sources cover the question, answer from them even if the "
    "topic isn't strictly about the CPMAI methodology."
)


class ContentHandler:
    name = "content"

    def __init__(self, db, provider: LLMProvider):
        self.db = db; self.provider = provider

    def respond(self, request, user) -> dict:
        chunks = retrieve_context(
            self.db, request.message,
            source_types=["question_explanation",
                           *SHARED_KNOWLEDGE_SOURCES])
        context = build_context_block(chunks)
        base_system = configurable_handler_system(self.name, DEFAULT_SYSTEM)
        base = (base_system + "\n\n" + context) if context else base_system
        system = with_preamble(base)
        history = [{"role": m.role, "content": m.content} for m in request.history]
        history.append({"role": "user", "content": request.message})
        text = self.provider.complete(system, history)
        return {"message": text,
                "citations": to_citations(chunks),
                "suggested_actions": []}
