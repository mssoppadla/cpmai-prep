"""OpenAI provider — uses chat.completions.

Lazily imports openai so the package isn't a hard dependency.
"""
from app.services.assistant.providers.base import LLMProvider


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str, api_key: str | None = None,
                 base_url: str | None = None, **config):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("openai package not installed") from e
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url) if api_key else None
        self.config = config

    def complete(self, system: str, messages: list[dict], **kwargs) -> str:
        if not self.client:
            raise RuntimeError("OpenAI provider not configured (missing API key)")
        msgs = [{"role": "system", "content": system}] + messages
        resp = self.client.chat.completions.create(
            model=self.model, messages=msgs,
            temperature=self.config.get("temperature", 0.3),
            max_tokens=self.config.get("max_tokens", 1500),
        )
        return resp.choices[0].message.content or ""
