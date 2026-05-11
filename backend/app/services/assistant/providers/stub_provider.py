"""Stub provider — used when no real LLM is configured.

Returns a single admin-configurable message so end users see something
friendly (rather than the dev-facing placeholder we used to ship). Admin
edits the message at /admin/settings → key `assistant.no_provider_message`.
"""
from app.core.settings_store import settings_store
from app.services.assistant.providers.base import LLMProvider


# Fallback when the setting hasn't been seeded yet. Kept generic — no
# mention of "admin", "provider", or other operator vocabulary.
_DEFAULT_MESSAGE = (
    "Our AI tutor is being set up right now and isn't able to answer "
    "questions yet. Please check back shortly — sorry for the wait."
)


class StubProvider(LLMProvider):
    name = "stub"

    def __init__(self, model: str = "stub-v1", **_):
        self.model = model

    def complete(self, system: str, messages: list[dict], **kwargs) -> str:
        return settings_store.get_str(
            "assistant.no_provider_message", _DEFAULT_MESSAGE)
