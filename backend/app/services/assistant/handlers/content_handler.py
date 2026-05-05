from app.services.assistant.providers.base import LLMProvider

SYSTEM = (
    "You explain CPMAI concepts (the 6-phase methodology) clearly and concisely. "
    "Use plain language; analogies are welcome."
)


class ContentHandler:
    def __init__(self, db, provider: LLMProvider):
        self.db = db; self.provider = provider

    def respond(self, request, user) -> dict:
        history = [{"role": m.role, "content": m.content} for m in request.history]
        history.append({"role": "user", "content": request.message})
        return {"message": self.provider.complete(SYSTEM, history),
                "citations": [], "suggested_actions": []}
