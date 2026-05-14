"""Type + registry contract for the agentic tool system.

These tests pin the SHAPES that the orchestrator (next PR) will rely
on. If anything here breaks, the orchestrator's contract with its
tools is broken too — much louder failure now is better than a
mysterious orchestrator runtime error later.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services.assistant.agentic import registry
from app.services.assistant.agentic.types import (
    Tool, ToolContext, ToolResult, ToolStatus, coerce_args,
)


# ----------------------------------------------------------- fixtures

class _DummyTool(Tool):
    """Minimal Tool subclass for shape-of-the-base-class tests."""
    name = "dummy"
    description = "Stub for tests"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "topk":  {"type": "integer"},
        },
        "required": ["query"],
    }

    def execute(self, ctx, args):
        return ToolResult(tool_name=self.name, status=ToolStatus.OK,
                           content=f"echo: {args.get('query')}")


# ============================================================ ToolResult

def test_tool_result_ok_property_only_true_for_ok_status():
    """``.ok`` should be sugar for ``status is OK`` — not OK for
    EMPTY/ERROR/REFUSED_NEED_AUTH (each of which has its own
    synthesis behaviour)."""
    assert ToolResult("t", ToolStatus.OK).ok is True
    assert ToolResult("t", ToolStatus.EMPTY).ok is False
    assert ToolResult("t", ToolStatus.ERROR, error="x").ok is False
    assert ToolResult("t", ToolStatus.REFUSED_NEED_AUTH).ok is False


def test_tool_result_default_fields_are_safe():
    """Empty defaults — synthesis treats missing list/dict fields as
    'this tool didn't produce any', so the defaults must be empty
    collections, not None."""
    r = ToolResult("t", ToolStatus.OK)
    assert r.citations == []
    assert r.suggested_actions == []
    assert r.error is None
    assert r.metadata == {}


# ============================================================ Tool.to_openai_schema

def test_to_openai_schema_matches_function_calling_shape():
    """OpenAI's tools[] array expects this exact wrapper. If we
    rename a key here, the router LLM stops seeing our tools."""
    schema = _DummyTool().to_openai_schema()
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "dummy"
    assert fn["description"] == "Stub for tests"
    assert fn["parameters"] == _DummyTool.parameters_schema


# ============================================================ coerce_args

def test_coerce_args_passes_through_valid_args():
    t = _DummyTool()
    cleaned, err = coerce_args(t, {"query": "hello", "topk": 5})
    assert err is None
    assert cleaned == {"query": "hello", "topk": 5}


def test_coerce_args_drops_unknown_keys():
    """Forward-compat: a router-supplied key the deployed tool
    doesn't know about gets silently dropped rather than failing."""
    t = _DummyTool()
    cleaned, err = coerce_args(t, {"query": "hi", "future_key": True})
    assert err is None
    assert "future_key" not in cleaned


def test_coerce_args_flags_missing_required():
    t = _DummyTool()
    cleaned, err = coerce_args(t, {"topk": 3})
    assert err is not None
    assert "query" in err


def test_coerce_args_coerces_int_string_to_int():
    """Router occasionally emits a number as a string. Cheap coercion
    at the boundary keeps tool bodies clean."""
    t = _DummyTool()
    cleaned, err = coerce_args(t, {"query": "x", "topk": "7"})
    assert err is None
    assert cleaned["topk"] == 7


def test_coerce_args_leaves_int_string_on_unparseable():
    """If we can't coerce, leave the value alone — the tool will
    surface its own error rather than the coerce step lying."""
    t = _DummyTool()
    cleaned, err = coerce_args(t, {"query": "x", "topk": "abc"})
    assert err is None
    # Left as the original string for the tool to handle/reject.
    assert cleaned["topk"] == "abc"


# ============================================================ registry

@pytest.fixture
def isolated_registry():
    """Snapshot + clear the registry around each test so we don't
    leak fake tools into other tests that rely on the real seven."""
    from app.services.assistant.agentic import registry as r
    snapshot = dict(r._registry)
    r._registry.clear()
    yield
    r._registry.clear()
    r._registry.update(snapshot)


def test_register_adds_tool_to_registry(isolated_registry):
    t = _DummyTool()
    registry.register(t)
    assert registry.get("dummy") is t
    assert "dummy" in registry.all_names()


def test_register_rejects_name_collisions(isolated_registry):
    """Two different instances claiming the same name → error.
    Programmer-error class — silently shadowing would be much worse
    than a loud import-time crash."""
    registry.register(_DummyTool())

    class Other(_DummyTool):  # same `name`, different class
        pass
    with pytest.raises(ValueError, match="collision"):
        registry.register(Other())


def test_register_is_idempotent_on_same_instance(isolated_registry):
    """Re-importing the same module (e.g., a test reload) should not
    crash — registering the same instance twice is a no-op."""
    t = _DummyTool()
    registry.register(t)
    registry.register(t)
    assert registry.get("dummy") is t


def test_get_returns_none_for_unknown(isolated_registry):
    assert registry.get("nope") is None


def test_replace_swaps_the_registry(isolated_registry):
    t = _DummyTool()
    registry.replace([t])
    assert registry.all_names() == ["dummy"]


# ============================================================ "all 7 ship" contract

def test_default_registry_contains_all_seven_tools():
    """Trigger imports so the per-tool ``register(...)`` lines fire,
    then assert every tool we promised in the architecture doc is
    actually wired up. Catches "forgot to add the new tool to
    tools/__init__.py" at test time, not in prod."""
    from app.services.assistant.agentic import tools  # noqa: F401
    names = set(registry.all_names())
    expected = {
        "faq_search", "content_search", "pricing_lookup",
        "account_state", "user_insights",
        "pmi_reference", "human_escalation",
    }
    missing = expected - names
    assert not missing, (
        f"tools missing from registry: {sorted(missing)}. "
        "Add an import line to "
        "app/services/assistant/agentic/tools/__init__.py.")


def test_each_tool_has_a_valid_openai_schema():
    """Every shipped tool must render to OpenAI's function-calling
    shape correctly — non-empty name, non-empty description, an
    object-typed parameters schema."""
    from app.services.assistant.agentic import tools  # noqa: F401
    for tool in registry.all_tools():
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"], tool
        assert fn["description"], tool
        assert fn["parameters"]["type"] == "object", tool
