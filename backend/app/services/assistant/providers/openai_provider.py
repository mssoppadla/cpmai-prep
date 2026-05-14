"""OpenAI provider — uses chat.completions, with tool-calling support.

Lazily imports openai so the package isn't a hard dependency.
"""
import json

from app.services.assistant.providers.base import (
    LLMProvider, ToolCall, ToolCallingResponse,
)


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

    def complete_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        **kwargs,
    ) -> ToolCallingResponse:
        """OpenAI function-calling completion.

        ``tools`` must already be in OpenAI's tools[] shape (the
        agentic registry produces these via Tool.to_openai_schema).
        We pass them through unchanged and surface the model's
        decision back as a :class:`ToolCallingResponse`.

        Arg-parsing: OpenAI returns ``tool_calls[i].function.arguments``
        as a JSON STRING (because the model emits valid JSON, not
        Python). We ``json.loads`` it at the boundary so callers see
        a dict. Malformed JSON → empty dict + ToolCall preserved
        (lets the orchestrator's coerce_args step report the missing
        required arg cleanly instead of crashing on a parse exception).
        """
        if not self.client:
            raise RuntimeError("OpenAI provider not configured (missing API key)")
        msgs = [{"role": "system", "content": system}] + messages
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=msgs,
            tools=tools,
            tool_choice="auto",
            temperature=self.config.get("temperature", 0.3),
            max_tokens=self.config.get("max_tokens", 1500),
        )
        choice = resp.choices[0]
        text = choice.message.content or ""
        tool_calls: list[ToolCall] = []
        for tc in (choice.message.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                # Model produced unparseable JSON. Keep the call so
                # the orchestrator can report "tool X missing args"
                # via the standard error path instead of dropping the
                # invocation silently.
                args = {}
            tool_calls.append(ToolCall(
                id=tc.id, name=tc.function.name, args=args,
            ))
        return ToolCallingResponse(
            text=text,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
        )
