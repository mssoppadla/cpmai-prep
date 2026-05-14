"""Process-wide registry of agentic tools.

The agentic orchestrator iterates over a single registry to:

  1. Build the ``tools[]`` array sent to the router LLM
     (one ``to_openai_schema()`` entry per registered tool).
  2. Look up the Tool instance for a router-emitted tool_call.

Tools register themselves at import time via :func:`register`. The
``app.services.assistant.agentic.tools`` package's ``__init__`` then
imports each tool module, which has the side-effect of populating
the registry. Two consequences:

  * The registry is "what's importable", not "what's enumerated in a
    list somewhere else" — adding a new tool means dropping a file
    into ``tools/`` and adding an import to ``tools/__init__.py``.
  * Tests can clear-and-replace the registry to exercise a controlled
    tool set (see :func:`clear` and :func:`replace`).

Thread-safety: registration happens at module import (single-threaded
in CPython's import lock); lookups after that are read-only.
"""
from __future__ import annotations

from typing import Iterable

from app.services.assistant.agentic.types import Tool


# Module-level singleton. Keyed by Tool.name (which the router uses to
# reference the tool in tool_calls — must be unique).
_registry: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    """Add a tool to the registry.

    Returns the tool unchanged so callers can use this as a decorator
    on the instance line::

        register(FaqSearchTool())

    Duplicate names raise — this is a programmer error, not a runtime
    condition. A re-registration usually means two modules accidentally
    use the same ``name`` constant.
    """
    if tool.name in _registry:
        existing = _registry[tool.name]
        if existing is tool:
            # Idempotent re-import (e.g., test reload) — silently OK.
            return tool
        raise ValueError(
            f"Tool name collision: '{tool.name}' is already registered "
            f"by {type(existing).__name__}. New registration "
            f"({type(tool).__name__}) would shadow it.")
    _registry[tool.name] = tool
    return tool


def get(name: str) -> Tool | None:
    """Look up a tool by name. Returns None if not registered.

    The orchestrator handles None as "router hallucinated a tool that
    doesn't exist" — a synth-time error rather than an exception."""
    return _registry.get(name)


def all_tools() -> list[Tool]:
    """Snapshot of every registered tool. Used for building the
    router's tools[] array.

    Returns a list (not the underlying dict) so callers can sort /
    filter without mutating the registry."""
    return list(_registry.values())


def all_names() -> list[str]:
    """Stable list of registered tool names — useful for debugging
    and for log messages that want a deterministic order."""
    return sorted(_registry.keys())


def clear() -> None:
    """Empty the registry. **Test-only** — production code should
    never call this. Tests use this in fixture setup to control
    exactly which tools are visible to the orchestrator under test."""
    _registry.clear()


def replace(tools: Iterable[Tool]) -> None:
    """Clear and re-register an exact set of tools.

    Useful in tests when you want the orchestrator to see, say, only
    a single mock tool. Equivalent to ``clear()`` followed by N
    ``register()`` calls.
    """
    clear()
    for t in tools:
        register(t)
