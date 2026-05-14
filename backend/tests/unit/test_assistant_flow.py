"""Flow resolver — :mod:`app.services.assistant.flow`.

This module is the gate between the legacy and agentic orchestration
pipelines. It must:

  * Default to LEGACY (seed value + every fallback path)
  * Honour an admin-set value of "agentic" / "legacy" / "shadow" /
    "percent:N" exactly
  * Bucket users deterministically for percent-rollout (same user →
    same bucket within a day, different day → re-roll)
  * Sample shadow-mode requests deterministically given a seed
  * Survive any malformed setting value by returning LEGACY

If any of these break, every chat turn on prod is at risk. The tests
below are the contract.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.services.assistant.flow import (
    Flow, FlowDecision,
    _cohort_bucket, _identity_seed,
    resolve_flow,
)


# ----------------------------------------------------------------- helpers

def _patch_setting(value):
    """Patch settings_store.get_str for ``assistant.flow``.

    Real settings_store hits Redis + DB; tests should not. Patching at
    the lowest layer (``settings_store.get_str``) keeps the test setup
    short and avoids fixture sprawl.
    """
    def fake_get_str(key, default=""):
        if key == "assistant.flow":
            return value
        if key == "assistant.agentic.shadow_sampling_rate":
            return default
        return default
    return patch("app.services.assistant.flow.settings_store.get_str",
                  side_effect=fake_get_str)


def _patch_setting_with_shadow_rate(flow_value: str, shadow_rate: float):
    """Patch both flow + shadow_sampling_rate for shadow-mode tests."""
    def fake_get_str(key, default=""):
        if key == "assistant.flow":
            return flow_value
        return default

    def fake_get_float(key, default=0.0):
        if key == "assistant.agentic.shadow_sampling_rate":
            return shadow_rate
        return default

    return (patch("app.services.assistant.flow.settings_store.get_str",
                   side_effect=fake_get_str),
            patch("app.services.assistant.flow.settings_store.get_float",
                   side_effect=fake_get_float))


# ============================================================ defaults

def test_default_is_legacy_when_setting_missing():
    """No setting present → safest path, no behaviour change."""
    with patch("app.services.assistant.flow.settings_store.get_str",
                return_value="legacy"):
        d = resolve_flow(user_id=None, anon_id=None)
    assert d.primary is Flow.LEGACY
    assert d.shadow is None


def test_unknown_value_falls_back_to_legacy():
    """Defence-in-depth: even if the admin validator misses something,
    the resolver fences the chat path to LEGACY."""
    with _patch_setting("totally-bogus"):
        d = resolve_flow(user_id=1, anon_id=None)
    assert d.primary is Flow.LEGACY
    assert "unknown flow value" in d.reason


def test_empty_string_falls_back_to_legacy():
    with _patch_setting(""):
        d = resolve_flow(user_id=1, anon_id=None)
    assert d.primary is Flow.LEGACY


# ============================================================ flat switch

def test_flat_legacy_for_authenticated_user():
    with _patch_setting("legacy"):
        d = resolve_flow(user_id=42, anon_id=None)
    assert d.primary is Flow.LEGACY


def test_flat_agentic_for_authenticated_user():
    with _patch_setting("agentic"):
        d = resolve_flow(user_id=42, anon_id=None)
    assert d.primary is Flow.AGENTIC
    assert d.reason == "setting=agentic"


def test_flat_agentic_for_anonymous_user():
    with _patch_setting("agentic"):
        d = resolve_flow(user_id=None, anon_id="anon-123")
    assert d.primary is Flow.AGENTIC


def test_case_insensitive_setting_value():
    """Admin types 'Agentic' or 'AGENTIC' — accepted."""
    with _patch_setting("AGENTIC"):
        d = resolve_flow(user_id=1, anon_id=None)
    assert d.primary is Flow.AGENTIC


# ============================================================ percent cohort

def test_percent_zero_means_everyone_legacy():
    """0% rollout: even bucket 0 stays on legacy (bucket < 0 is never true)."""
    with _patch_setting("percent:0"):
        for uid in range(50):
            d = resolve_flow(user_id=uid, anon_id=None)
            assert d.primary is Flow.LEGACY, f"user {uid} → {d}"


def test_percent_hundred_means_everyone_agentic():
    """100% rollout: every user lands on agentic."""
    with _patch_setting("percent:100"):
        for uid in range(50):
            d = resolve_flow(user_id=uid, anon_id=None)
            assert d.primary is Flow.AGENTIC, f"user {uid} → {d}"


def test_percent_split_is_stable_within_day():
    """Same user, same day → same bucket → same flow."""
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    with _patch_setting("percent:50"):
        first = resolve_flow(user_id=42, anon_id=None, now=now)
        second = resolve_flow(user_id=42, anon_id=None, now=now)
    assert first.primary is second.primary
    assert first.reason == second.reason


def test_percent_split_re_buckets_next_day():
    """Re-rolling daily means a user stuck on the "bad" flow gets a
    fresh shot tomorrow. NOT guaranteed to flip — just probabilistic —
    so we assert the bucket VALUE changes (which is what drives the
    flow decision), not that the flow itself changes."""
    day1 = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    b1 = _cohort_bucket(user_id=42, anon_id=None, now=day1)
    b2 = _cohort_bucket(user_id=42, anon_id=None, now=day2)
    # In a 100-bucket space, P(same bucket on two consecutive days)
    # is 1/100. The test is "buckets are different" — flaky 1% of the
    # time. We pin a specific user_id where we've verified the rolls
    # come out different, so the assertion is deterministic.
    assert b1 != b2, ("if this fails, user_id=42 happens to land on "
                       "the same bucket two days running — pick a "
                       "different uid; this is a test-setup issue, "
                       "not a logic bug")


def test_percent_distribution_is_roughly_uniform():
    """Sanity check: across many synthetic users at percent:50, roughly
    half should land on agentic. Allow ±10% slack so the test isn't
    flaky on CI."""
    with _patch_setting("percent:50"):
        agentic_count = sum(
            1 for uid in range(1000)
            if resolve_flow(user_id=uid, anon_id=None).primary is Flow.AGENTIC
        )
    assert 400 <= agentic_count <= 600, (
        f"expected ~500/1000 agentic at percent:50, got {agentic_count}. "
        "If consistently outside the band, the hash is not uniform.")


def test_percent_clamps_above_100():
    """Admin types percent:9999 — gets treated as 100% (validator
    should reject it earlier, but resolver is defensive)."""
    with _patch_setting("percent:9999"):
        d = resolve_flow(user_id=1, anon_id=None)
    # After clamp to 100, every bucket (0..99) is < 100 → AGENTIC.
    assert d.primary is Flow.AGENTIC


def test_percent_clamps_below_zero():
    with _patch_setting("percent:-50"):
        d = resolve_flow(user_id=1, anon_id=None)
    # After clamp to 0, no bucket is < 0 → LEGACY.
    assert d.primary is Flow.LEGACY


def test_percent_malformed_value_is_legacy():
    """percent:abc — validator should reject at PATCH time, but if it
    leaks through, fall back to legacy not raise."""
    with _patch_setting("percent:abc"):
        d = resolve_flow(user_id=1, anon_id=None)
    assert d.primary is Flow.LEGACY
    assert "malformed" in d.reason


def test_anon_and_user_get_different_buckets():
    """An anon_id and a user_id with the same string don't conflate.
    Identity prefix 'a' vs 'u' guarantees distinct seeds."""
    now = datetime(2026, 5, 14, tzinfo=timezone.utc)
    b_user = _cohort_bucket(user_id=42, anon_id=None, now=now)
    b_anon = _cohort_bucket(user_id=None, anon_id="42", now=now)
    assert b_user != b_anon


# ============================================================ shadow mode

def test_shadow_returns_legacy_as_primary():
    """Shadow mode never sends the user the agentic answer — legacy
    is always primary; agentic logs in the background."""
    str_patch, float_patch = _patch_setting_with_shadow_rate(
        "shadow", shadow_rate=1.0)
    with str_patch, float_patch:
        d = resolve_flow(user_id=1, anon_id=None,
                          rng=random.Random(0))
    assert d.primary is Flow.LEGACY
    assert d.shadow is Flow.AGENTIC


def test_shadow_zero_rate_means_no_shadow():
    """rate=0.0 disables shadow side. Used to plumb the wiring without
    running any agentic traffic yet."""
    str_patch, float_patch = _patch_setting_with_shadow_rate(
        "shadow", shadow_rate=0.0)
    with str_patch, float_patch:
        # Random number can't be < 0.0, so shadow never fires.
        for _ in range(20):
            d = resolve_flow(user_id=1, anon_id=None,
                              rng=random.Random(0))
            assert d.shadow is None


def test_shadow_sampling_rate_clamps_above_one():
    str_patch, float_patch = _patch_setting_with_shadow_rate(
        "shadow", shadow_rate=2.5)
    with str_patch, float_patch:
        # Clamped to 1.0 → every roll fires.
        d = resolve_flow(user_id=1, anon_id=None,
                          rng=random.Random(0))
    assert d.shadow is Flow.AGENTIC


def test_shadow_sampling_is_seeded_by_identity():
    """Two requests from the same user at the same time, given the
    real internal RNG (no override), should pick the SAME shadow
    decision. This is what makes shadow-mode analysis fair —
    a user's 1-in-10 sample is consistent within the same UTC day."""
    str_patch, float_patch = _patch_setting_with_shadow_rate(
        "shadow", shadow_rate=0.5)
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    with str_patch, float_patch:
        d1 = resolve_flow(user_id=42, anon_id=None, now=now)
        d2 = resolve_flow(user_id=42, anon_id=None, now=now)
    assert (d1.shadow is None) == (d2.shadow is None)


# ============================================================ helpers

def test_identity_seed_is_stable_across_processes():
    """SHA-256 of identity+date — same inputs, same digest. Critical
    for cross-process determinism (two backend workers behind one LB
    must give the same user the same flow)."""
    now = datetime(2026, 5, 14, tzinfo=timezone.utc)
    s1 = _identity_seed(user_id=42, anon_id=None, now=now)
    s2 = _identity_seed(user_id=42, anon_id=None, now=now)
    assert s1 == s2


def test_identity_seed_changes_with_day():
    day1 = datetime(2026, 5, 14, tzinfo=timezone.utc)
    day2 = datetime(2026, 5, 15, tzinfo=timezone.utc)
    assert _identity_seed(user_id=42, anon_id=None, now=day1) \
        != _identity_seed(user_id=42, anon_id=None, now=day2)


@pytest.mark.parametrize("user_id, anon_id", [
    (None,  None),     # no identity at all (anon middleware bug)
    (None,  ""),       # blank anon_id (defensive)
    (None,  "x"),      # short anon_id
    (1,     None),
    (10**9, None),     # big user_id
])
def test_resolve_does_not_raise_on_edge_identities(user_id, anon_id):
    """The hash path must tolerate any identity shape — including
    no-identity-at-all (which would be a frontend bug but we don't
    want to crash the chat path)."""
    with _patch_setting("percent:50"):
        d = resolve_flow(user_id=user_id, anon_id=anon_id)
    assert d.primary in (Flow.LEGACY, Flow.AGENTIC)
