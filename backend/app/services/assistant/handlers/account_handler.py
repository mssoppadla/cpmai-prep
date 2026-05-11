"""Account handler — pricing, plans, billing questions.

Retrieves from the `plan` source so price changes show up immediately
(plan reindex runs on each save). Suggested action surfaces a deep
link to the /pricing page for the matching plan.
"""
from app.services.assistant.providers.base import LLMProvider
from app.services.assistant.rag.handler_support import (
    build_context_block, retrieve_context, to_citations,
)


SYSTEM = (
    "You answer questions about CPMAI Prep accounts, subscriptions, billing, "
    "pricing, and payment plans. Be concise. Always cite the specific plan "
    "(name + price) when relevant. Never reveal another user's details."
)


class AccountHandler:
    def __init__(self, db, provider: LLMProvider):
        self.db = db
        self.provider = provider

    def respond(self, request, user) -> dict:
        chunks = retrieve_context(
            self.db, request.message, source_types=["plan"])
        context = build_context_block(chunks)
        system = (SYSTEM + "\n\n" + context) if context else SYSTEM
        history = [{"role": m.role, "content": m.content} for m in request.history]
        history.append({"role": "user", "content": request.message})
        text = self.provider.complete(system, history)
        return {"message": text,
                "citations": to_citations(chunks),
                "suggested_actions": [{"label": "View pricing", "url": "/pricing"}]
                                       if chunks else []}
