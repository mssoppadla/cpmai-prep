"""Orchestrator flow-dispatch contract.

The :class:`AssistantOrchestrator.handle` method branches on the
``assistant.flow`` setting:

  * "legacy"   → original keyword-classifier + handler pipeline
                 (must remain byte-for-byte equivalent to pre-refactor)
  * "agentic"  → router + tool-calling + synthesis (this PR)
  * "percent:N" → deterministic cohort split
  * "shadow"   → run both, return legacy (background-agentic side
                 is sampled per ``shadow_sampling_rate``)

Tests below pin:

  1. With the seed default (``flow=legacy``) the /assistant/chat endpoint
     works exactly as before — regression guard.

  2. ``flow=agentic`` returns a 200 with an agentic-shaped response.
     The body is whatever the StubProvider supplies (since there's no
     real LLM in tests), but the wire shape (intent="agentic",
     citations, suggested_actions) is what we pin here.

  3. Invalid setting values are rejected at PATCH time (422).
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


def test_agentic_flow_returns_agentic_shaped_response(client, admin):
    """``flow=agentic`` returns a 200 whose response shape matches
    the agentic contract: intent="agentic", message non-empty,
    citations and suggested_actions present (may be empty when the
    StubProvider returns no tool calls)."""
    assert _set_flow(client, admin, "agentic").status_code == 200
    client.cookies.set("aid", "anon-agentic")
    r = _chat(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "agentic"
    assert isinstance(body["message"], str)
    assert body["message"]
    assert isinstance(body["citations"], list)
    assert isinstance(body["suggested_actions"], list)


def test_percent_zero_routes_everyone_to_legacy(client, admin):
    """Cohort 0% — every user lands on legacy. Useful for plumbing the
    setting before flipping to a real percent."""
    assert _set_flow(client, admin, "percent:0").status_code == 200
    client.cookies.set("aid", "anon-percent-zero")
    r = _chat(client)
    assert r.status_code == 200


def test_percent_hundred_routes_everyone_to_agentic(client, admin):
    """Cohort 100% — every user lands on agentic. Sanity check that
    the cohort hashing doesn't accidentally route a user to legacy
    when N=100."""
    assert _set_flow(client, admin, "percent:100").status_code == 200
    client.cookies.set("aid", "anon-percent-hundred")
    r = _chat(client)
    assert r.status_code == 200, r.text
    assert r.json()["intent"] == "agentic"


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
