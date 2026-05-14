"""FAQ handler — grounds responses in the CPMAI FAQ corpus + admin-uploaded
documents.

Retrieves the top-k matching chunks via RAG (from both ``faq`` rows and
the shared uploaded-document pool), prepends them to the system prompt,
asks the LLM to answer + cite. Falls through to a bare-LLM answer if
RAG is empty (mid-rollout / OpenAI hiccup) — the chat stays useful
instead of failing closed.

Why the upload corpus is in scope here too: an admin uploading a
"CPMAI knowledge base" doc expects the assistant to answer from it.
Without folding the ``upload`` source into our retrieval set, those
chunks would sit in rag_chunks unread by any handler — orphaned
embeddings cost money and surface zero value. The admin-curated
upload pool is shared across topical handlers so ANY question that
gets routed here can pull from it. (See SHARED_KNOWLEDGE_SOURCES
in handler_support.py for the exact set.)
"""
from app.services.assistant.providers.base import LLMProvider
from app.services.assistant.rag.handler_support import (
    SHARED_KNOWLEDGE_SOURCES,
    build_context_block, retrieve_context, to_citations,
)
from app.services.assistant.system_prompt import (
    configurable_handler_system, with_preamble,
)


# Hardcoded fallback. The active prompt is admin-editable via
# `assistant.handler.faq.system` (Runtime Settings → AI assistant
# group). This constant is what's used when the setting is empty —
# matches what the bot did before the setting existed.
DEFAULT_SYSTEM = (
    "You answer factual questions about the CPMAI certification process — "
    "eligibility, exam format, scoring, scheduling — AND any topic "
    "covered by the admin-uploaded reference materials in the provided "
    "sources. Be concise and accurate. Treat the provided sources as "
    "authoritative; if the sources cover the question, answer from them "
    "even if the topic isn't strictly about CPMAI certification process. "
    "If the provided sources don't cover the question, say you don't know "
    "rather than guess."
)


class FAQHandler:
    name = "faq"   # also the settings-key segment: assistant.handler.faq.system

    def __init__(self, db, provider: LLMProvider):
        self.db = db; self.provider = provider

    def respond(self, request, user) -> dict:
        chunks = retrieve_context(
            self.db, request.message,
            source_types=["faq", *SHARED_KNOWLEDGE_SOURCES])
        context = build_context_block(chunks)
        base_system = configurable_handler_system(self.name, DEFAULT_SYSTEM)
        base = (base_system + "\n\n" + context) if context else base_system
        # Prepend admin-configured guardrails (preamble + allowed/banned).
        system = with_preamble(base)
        history = [{"role": m.role, "content": m.content} for m in request.history]
        history.append({"role": "user", "content": request.message})
        text = self.provider.complete(system, history)
        return {"message": text,
                "citations": to_citations(chunks),
                "suggested_actions": []}
