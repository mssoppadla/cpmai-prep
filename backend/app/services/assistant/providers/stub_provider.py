from app.services.assistant.providers.base import LLMProvider


class StubProvider(LLMProvider):
    name = "stub"

    def __init__(self, model: str = "stub-v1", **_):
        self.model = model

    def complete(self, system: str, messages: list[dict], **kwargs) -> str:
        last = messages[-1]["content"] if messages else ""
        return (
            "🤖 (placeholder) Real AI is not configured. "
            f'I received: "{last[:160]}". '
            "An admin can wire up a real provider in the LLM Providers admin panel."
        )
