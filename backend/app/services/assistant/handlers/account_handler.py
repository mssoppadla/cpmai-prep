from app.services.assistant.providers.base import LLMProvider


SYSTEM = (
    "You answer questions about CPMAI Prep accounts, subscriptions, billing, "
    "and payments. Be concise. Never reveal another user's details."
)


class AccountHandler:
    def __init__(self, db, provider: LLMProvider):
        self.db = db
        self.provider = provider

    def respond(self, request, user) -> dict:
        history = [{"role": m.role, "content": m.content} for m in request.history]
        history.append({"role": "user", "content": request.message})
        text = self.provider.complete(SYSTEM, history)
        return {"message": text, "citations": [], "suggested_actions": []}
