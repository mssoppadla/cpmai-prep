"""LLM-provider abstraction.

Two calling modes:

  * ``complete(system, messages) -> str``
      Plain text completion. Used by every legacy handler and by
      the agentic synthesis node.

  * ``complete_with_tools(system, messages, tools) -> ToolCallingResponse``
      Function-calling completion. Used by the agentic router node.
      Default implementation raises — providers that don't support
      tool calling are still usable for plain ``complete()``. The
      OpenAI provider overrides this; the Stub provider returns an
      empty tool_calls list so it's safely callable in tests.

This module deliberately stays tiny + framework-agnostic. The
``ToolCall`` / ``ToolCallingResponse`` shapes mirror OpenAI's
function-calling response with names normalised away from vendor
specifics, so adding an Anthropic implementation is a translation
job, not a refactor of every caller.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A single tool invocation the LLM has requested.

    Attributes:
      id:    Vendor-specific call ID (e.g. ``call_abc123`` from
             OpenAI). Echoed back when we feed the tool result
             into a follow-up call. Tests can pass any string.
      name:  The tool's name — must match a registered Tool.name
             in :mod:`app.services.assistant.agentic.registry`.
      args:  Parsed JSON arguments. Coerced from the vendor's
             arguments-string at provider boundary so callers
             see a plain dict.
    """
    id:   str
    name: str
    args: dict[str, Any]


@dataclass
class ToolCallingResponse:
    """Result of a ``complete_with_tools`` call.

    Attributes:
      text:           Assistant's text content. Empty when the
                      model finished with tool calls; populated
                      when it answered directly without picking
                      a tool (e.g. for "hi" / "thanks" turns).
      tool_calls:     Tools the LLM wants invoked. Empty list
                      means "answer directly using ``text``".
      finish_reason:  Vendor's finish reason — ``"stop"`` when
                      no tool calls, ``"tool_calls"`` when there
                      are tool calls to execute, others
                      (``"length"`` etc.) on edge cases.
    """
    text:          str
    tool_calls:    list[ToolCall] = field(default_factory=list)
    finish_reason: str            = "stop"


class LLMProvider(ABC):
    name: str = "base"
    model: str | None = None

    @abstractmethod
    def complete(self, system: str, messages: list[dict], **kwargs) -> str:
        """Plain text completion — used by legacy handlers + synthesis."""

    def complete_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        **kwargs,
    ) -> ToolCallingResponse:
        """Tool-calling completion.

        Providers that don't support tool calling can leave this
        unimplemented — callers will see a clear error rather than
        a silently broken agentic flow. The agentic orchestrator
        catches the exception and surfaces it via its drift-tag
        path (next PR), so a misconfigured provider is visible to
        operators in the dashboard.

        Implementations must:
          * Pass ``tools`` to the vendor unchanged (it's already
            been rendered to the vendor's expected shape via
            :meth:`Tool.to_openai_schema`).
          * Parse the vendor's arguments-string into a plain dict
            for each :class:`ToolCall`.
          * Treat a model that returns BOTH ``text`` and
            ``tool_calls`` as valid — synthesis can use the text
            as a preamble while still executing the tools.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support tool calling. "
            "Set assistant.flow=legacy or configure an OpenAI provider."
        )
