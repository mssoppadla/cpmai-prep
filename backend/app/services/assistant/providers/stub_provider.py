"""Stub provider — used when no real LLM is configured.

Returns a single admin-configurable message so end users see something
friendly (rather than the dev-facing placeholder we used to ship). Admin
edits the message at /admin/settings → key `assistant.no_provider_message`.
"""
from app.core.settings_store import settings_store
from app.services.assistant.providers.base import (
    LLMProvider, ToolCallingResponse,
)


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

    def complete_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        **kwargs,
    ) -> ToolCallingResponse:
        """Stub never picks tools — returns the configured message as
        plain text with an empty tool_calls list.

        Why: in tests where no real LLM is configured, the agentic
        orchestrator still needs SOME router response. Returning
        ``tool_calls=[]`` means the orchestrator falls through to
        "router answered directly" path and surfaces the admin's
        no-provider message as the user-facing answer. Tests that
        want to exercise a specific tool-calling path patch this
        method (or the provider) explicitly.
        """
        return ToolCallingResponse(
            text=settings_store.get_str(
                "assistant.no_provider_message", _DEFAULT_MESSAGE),
            tool_calls=[],
            finish_reason="stop",
        )
