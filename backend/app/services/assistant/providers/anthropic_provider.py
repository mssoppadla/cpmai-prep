"""Anthropic (Claude) provider — uses messages.create.

Lazily imports `anthropic` so the package isn't a hard dependency at
import time. The admin enables this provider by:
  1. Picking `provider_type: anthropic` in /admin/llm-providers
  2. Pasting an Anthropic API key (sk-ant-...)
  3. Setting model (e.g. claude-sonnet-4-5, claude-opus-4-7)
  4. Activating the provider

Note (Claude Max vs API): Claude Max is the consumer chat subscription
on claude.ai — it does NOT include API access. Separate billing.
Sign up for the API at console.anthropic.com to get an `sk-ant-...` key.
"""
from app.services.assistant.providers.base import LLMProvider


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str, api_key: str | None = None,
                 base_url: str | None = None, **config):
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError("anthropic package not installed") from e
        self.model = model
        # base_url override is optional — used for Anthropic-compatible
        # proxies (e.g. corporate gateways). Default goes to api.anthropic.com.
        self.client = (
            Anthropic(api_key=api_key, base_url=base_url) if base_url
            else Anthropic(api_key=api_key)
        ) if api_key else None
        self.config = config

    def complete(self, system: str, messages: list[dict], **kwargs) -> str:
        if not self.client:
            raise RuntimeError("Anthropic provider not configured (missing API key)")
        # Anthropic API takes system as a top-level kwarg, not in messages.
        # Roles in messages must be alternating user/assistant — passthrough
        # works as long as the orchestrator already produces that shape
        # (today it does: user-then-assistant, single user turn typically).
        resp = self.client.messages.create(
            model=self.model,
            system=system,
            messages=messages,
            max_tokens=self.config.get("max_tokens", 1500),
            temperature=self.config.get("temperature", 0.3),
        )
        # `content` is a list of content blocks; for plain text responses
        # we concatenate the text blocks. SDK >= 0.34 returns objects with
        # `.type == "text"` and `.text`.
        parts = []
        for block in resp.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)
