"""Orchestrator flow-dispatch contract.

The :class:`AssistantOrchestrator.handle` method now branches on the
``assistant.flow`` setting:

  * "legacy"   → original keyword-classifier + handler pipeline
                 (must remain byte-for-byte equivalent to pre-refactor)
  * "agentic"  → NotImplementedError until the follow-up PR lands

Tests below are the contract:

  1. With the seed default (``flow=legacy``) the /assistant/chat endpoint
     still works exactly as before — this is the regression guard.

  2. When an operator flips to ``flow=agentic`` BEFORE the implementation
     lands, the request fails cleanly (HTTP 500) rather than corrupting
     state. The seed default prevents this from happening on prod, but
     we test the guard explicitly so a future "set flow=agentic in
     staging accidentally" scenario can't ship without our knowing.

  3. Setting an invalid value falls back to legacy (defence-in-depth).
"""
import pytest


def _chat(client, **kwargs):
    return client.post("/api/v1/assistant/chat",
                       json={"message": "What is CPMAI?"}, **kwargs)


def _set_flow(client, admin, value):
    """Admin patches the setting. Round-trips through the real validator,
    so a value the validator rejects also gets rejected here."""
    from tests.conftest import auth_header
    h = auth_header(client, admin.email)
    r = client.patch("/api/v1/admin/settings/assistant.flow",
                      headers=h, json={"value": value})
    return r


def test_legacy_is_the_seed_default(client):
    """Anonymous user hitting /assistant/chat works with no admin
    intervention — the seed default routes everything through legacy."""
    client.cookies.set("aid", "anon-default-flow")
    r = _chat(client)
    assert r.status_code == 200
    # Response shape unchanged from before the dispatch branch.
    body = r.json()
    assert "message" in body
    assert "citations" in body
    assert "intent" in body


def test_explicit_legacy_setting_works_the_same(client, admin):
    """Operator types 'legacy' into the admin form (no-op vs default,
    but we exercise the round-trip)."""
    assert _set_flow(client, admin, "legacy").status_code == 200
    client.cookies.set("aid", "anon-explicit-legacy")
    r = _chat(client)
    assert r.status_code == 200


def test_agentic_flow_is_not_yet_implemented(client, admin):
    """Flipping flow=agentic BEFORE the agentic impl lands must fail
    cleanly. Seed default is 'legacy' so this scenario only happens if
    an operator opts in — but if they do, we don't want a corrupt state.

    The HTTP layer surfaces NotImplementedError as 500. When the agentic
    PR lands, this test changes to assert 200 with an agentic response
    (and a new test guards "flow=legacy still works")."""
    assert _set_flow(client, admin, "agentic").status_code == 200
    client.cookies.set("aid", "anon-agentic-not-impl")
    r = _chat(client)
    assert r.status_code == 500


def test_percent_zero_routes_everyone_to_legacy(client, admin):
    """Cohort 0% — every user lands on legacy. Useful for plumbing the
    setting before flipping to a real percent."""
    assert _set_flow(client, admin, "percent:0").status_code == 200
    client.cookies.set("aid", "anon-percent-zero")
    r = _chat(client)
    assert r.status_code == 200


def test_percent_hundred_would_route_everyone_to_agentic(client, admin):
    """Cohort 100% — every user lands on agentic, which today raises.
    Once the agentic PR ships, this asserts 200 instead."""
    assert _set_flow(client, admin, "percent:100").status_code == 200
    client.cookies.set("aid", "anon-percent-hundred")
    r = _chat(client)
    assert r.status_code == 500


def test_invalid_flow_value_is_rejected_by_admin_validator(client, admin):
    """The settings validator should refuse a value the resolver
    wouldn't understand — catch it at PATCH time, not chat time."""
    r = _set_flow(client, admin, "totally-bogus-flow")
    # 422 from the EDITABLE validator. The runtime resolver ALSO
    # falls back to legacy if a bad value somehow leaks past — see
    # test_unknown_value_falls_back_to_legacy in unit/test_assistant_flow.py.
    assert r.status_code == 422


def test_percent_value_out_of_range_rejected_by_admin_validator(client, admin):
    r = _set_flow(client, admin, "percent:9999")
    assert r.status_code == 422


def test_shadow_mode_still_returns_legacy_answer(client, admin):
    """In shadow mode the user always sees legacy. The agentic side
    runs in the background (gated by ``shadow_sampling_rate=0.0`` seed
    default, so today it doesn't actually fire — but the user-facing
    response shape is what matters here)."""
    assert _set_flow(client, admin, "shadow").status_code == 200
    client.cookies.set("aid", "anon-shadow-mode")
    r = _chat(client)
    assert r.status_code == 200
    # Legacy response shape — no agentic-specific keys leak through.
    body = r.json()
    assert "intent" in body
    assert "message" in body
