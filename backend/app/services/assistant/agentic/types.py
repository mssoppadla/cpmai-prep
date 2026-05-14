"""Tool interface for the agentic orchestrator.

A **Tool** is a deterministic function the router LLM can choose to
invoke. Each tool has:

  * a stable ``name``         — referenced by the router's tool_calls
  * a ``description``         — fed into the router's system prompt so
                                it knows when to pick this tool
  * a ``parameters_schema``   — JSON-schema fragment matching the
                                OpenAI function-calling format; lets
                                the router emit args the tool can
                                actually consume
  * an ``execute()``          — synchronously runs the tool against a
                                :class:`ToolContext`, returns a
                                :class:`ToolResult`

Tools must **never raise** out of ``execute`` — they catch their own
errors and return a ``ToolResult`` with ``status=ERROR``. This keeps
the LangGraph state-machine simple: one tool failing doesn't blow up
the whole agentic turn.

Design notes:

  * The interface is **provider-agnostic**. ``to_openai_schema()``
    renders to OpenAI's function-calling shape, but a future
    ``to_anthropic_schema()`` plugs into the same Tool class.
  * Tools that internally use an LLM (today: the RAG tools that do
    embedding calls) declare ``has_llm_call = True`` so the cost
    accounting in the audit log can sum embeddings vs generations
    separately when we want.
  * Tools that require an authenticated user declare
    ``requires_user = True``. The orchestrator checks this BEFORE
    invoking — short-circuits to a polite "please sign in" response
    instead of routing an anonymous request to a tool that would
    just return an error.
"""
from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User


class ToolStatus(str, enum.Enum):
    """Outcome of a tool invocation. The orchestrator uses this to
    decide whether synthesis should treat the result as evidence
    (OK / EMPTY) or as an error to communicate to the user (ERROR /
    REFUSED_NEED_AUTH)."""

    OK                = "ok"
    EMPTY             = "empty"               # ran cleanly, no results
    ERROR             = "error"               # caught exception inside the tool
    REFUSED_NEED_AUTH = "refused_need_auth"   # tool refuses because user is anon


@dataclass
class ToolContext:
    """Everything a tool needs to do its work, threaded as a single
    parameter so individual tools stay easy to test in isolation.

    Tools should treat ``user`` and ``anon_id`` as **optional** — even
    when ``requires_user=True`` the orchestrator pre-screens, but a
    defence-in-depth check inside the tool body keeps unit tests
    honest.
    """
    db: Session
    user: User | None
    anon_id: str | None


@dataclass
class ToolResult:
    """Output of a single tool call. The synthesis LLM concatenates
    these into its evidence block.

    Attributes:
      tool_name:         echoes the Tool.name that produced this — so
                         a tool_call id can be traced back through
                         logs without joining the call list.
      status:            see :class:`ToolStatus`.
      content:           prose / structured-text the synthesis LLM
                         reads. Empty string for pure-routing tools.
      citations:         passes through to the final AssistantResponse
                         so the user-facing chip list shows where the
                         answer came from. Matches the existing
                         AssistantCitation shape.
      suggested_actions: passes through to AssistantResponse. Tools
                         like ``pmi_reference`` populate this with a
                         deep-link button; others leave it empty.
      error:             human-readable error string when
                         status=ERROR. Synthesis can decide to surface
                         this or quietly swallow.
      metadata:          opaque dict logged with the tool call's
                         audit row. Useful for "did we retrieve N
                         chunks? hit cache?" debugging without
                         expanding the dataclass shape per tool.
    """
    tool_name: str
    status:    ToolStatus
    content:   str               = ""
    citations: list[dict]        = field(default_factory=list)
    suggested_actions: list[dict] = field(default_factory=list)
    error:     str | None        = None
    metadata:  dict[str, Any]    = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Convenience for ``if result.ok: …`` checks in synthesis."""
        return self.status is ToolStatus.OK


class Tool(ABC):
    """Base class for agentic tools.

    Implementations declare the class-level attributes ``name``,
    ``description``, and ``parameters_schema``, and define
    ``execute``. The registry imports the module once at startup;
    each module's ``register`` call adds the singleton instance to
    the active registry.

    Tools are stateless singletons. Per-request state (DB session,
    current user, anon_id) is passed via :class:`ToolContext`. This
    makes the registry safe to share across threads / async workers
    without locking.
    """
    name: str                              # e.g. "faq_search"
    description: str                       # surfaced to router LLM
    parameters_schema: dict[str, Any]      # JSON-schema object

    # Capability flags — orchestrator reads these for pre-flight
    # decisions (auth checks, cost accounting).
    requires_user: bool = False
    has_llm_call:  bool = False    # True for tools that embed internally

    @abstractmethod
    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        """Synchronously run the tool. Must NEVER raise — catch
        everything and return ToolResult(status=ERROR, error=...)."""

    def to_openai_schema(self) -> dict[str, Any]:
        """Render this tool as an OpenAI ``tools[]`` entry.

        The router LLM consumes this verbatim — keep ``description``
        and ``parameters_schema`` correct, and OpenAI's tool-calling
        does the rest. We may add ``to_anthropic_schema()`` later
        when a non-OpenAI provider lands.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


# ----------------------------------------------------- arg-validation helper
def coerce_args(tool: Tool, args: dict[str, Any]) -> tuple[dict, str | None]:
    """Lightweight JSON-schema validation against ``parameters_schema``.

    The router LLM is usually-correct but occasionally hallucinates
    arg shapes (missing required, wrong type, extra keys). We do a
    cheap check before calling ``execute`` so tool bodies don't need
    to defend against malformed input.

    Returns (cleaned_args, error_or_None). If error is set, the
    caller should construct a ToolResult(status=ERROR, error=...)
    instead of invoking ``execute``.

    Not strict — extra keys are silently dropped (forward-compat with
    a router that adds a parameter the deployed tool doesn't know
    yet). Missing required keys = error.
    """
    schema = tool.parameters_schema
    if schema.get("type") != "object":
        return args, None  # nothing to validate against
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    cleaned: dict[str, Any] = {}
    for k, spec in properties.items():
        if k in args:
            v = args[k]
            t = spec.get("type")
            # Permissive coercion: router sometimes emits a number as
            # a string. Cheap to fix here rather than in each tool.
            if t == "string" and not isinstance(v, str):
                v = str(v) if v is not None else None
            elif t == "integer" and isinstance(v, str):
                try: v = int(v)
                except ValueError: pass
            cleaned[k] = v

    missing = required - cleaned.keys()
    if missing:
        return cleaned, f"missing required args: {sorted(missing)}"
    return cleaned, None
