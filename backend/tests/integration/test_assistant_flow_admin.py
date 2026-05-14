"""Admin control plane for the assistant.flow toggle.

Two endpoints under ``/admin/assistant-flow``:

  * ``/state``    — one round-trip read of every flow-related setting
  * ``/preview``  — show which flow a given identity lands on now

Tests pin:

  * RBAC (admin-only)
  * Response shape (frontend depends on it)
  * State reflects PATCH changes via the existing /admin/settings
    endpoint (no separate write path; reuses the validator)
  * Preview is deterministic for a fixed identity within a UTC day
  * Preview shows the correct decision under each flow value
"""
from __future__ import annotations

import pytest

from tests.conftest import auth_header


@pytest.fixture(autouse=True)
def _reset_flow_settings_cache():
    """Settings_store has two cache layers — a module-level local
    dict (30s TTL) AND the (fakeredis-backed) Redis cache — both of
    which are PROCESS-WIDE singletons. Per-test isolation requires
    clearing both, since the per-test SQLite DB is empty for these
    keys and we want call-site defaults to come through.

    Without this reset, a prior test that PATCHed
    ``assistant.flow=percent:25`` leaves the value cached in Redis;
    a later test's ``settings_store.get`` hits Redis before the
    (empty) DB and returns the stale value."""
    from app.core.redis import redis_client
    from app.core.settings_store import CACHE_PREFIX, _local

    flow_keys = (
        "assistant.flow",
        "assistant.agentic.tools_max_calls",
        "assistant.agentic.router_system",
        "assistant.agentic.synthesis_system",
        "assistant.agentic.shadow_sampling_rate",
    )

    def _flush():
        for k in flow_keys:
            _local.pop(k, None)
            try:
                redis_client.delete(CACHE_PREFIX + k)
            except Exception:
                pass

    _flush()
    yield
    # Same on tear-down so subsequent tests in OTHER modules start
    # clean too — important when the suite is run with -p no:randomly
    # OR when pytest interleaves files.
    _flush()


def _set(client, admin, key, value):
    h = auth_header(client, admin.email)
    r = client.patch(f"/api/v1/admin/settings/{key}",
                      headers=h, json={"value": value})
    assert r.status_code == 200, r.text


# ============================================================ RBAC

def test_state_requires_admin(client, user):
    h = auth_header(client, user.email)
    r = client.get("/api/v1/admin/assistant-flow/state", headers=h)
    assert r.status_code in (401, 403)


def test_preview_requires_admin(client, user):
    h = auth_header(client, user.email)
    r = client.get("/api/v1/admin/assistant-flow/preview", headers=h)
    assert r.status_code in (401, 403)


# ============================================================ /state

class TestState:

    def test_returns_seed_defaults(self, client, admin):
        h = auth_header(client, admin.email)
        body = client.get(
            "/api/v1/admin/assistant-flow/state", headers=h).json()
        assert body["flow"] == "legacy"
        assert body["tools_max_calls"] == 4
        assert body["router_system"] == ""
        assert body["synthesis_system"] == ""
        assert body["shadow_sampling_rate"] == 0.0
        # Convenience flags
        assert body["is_agentic_reachable"] is False
        assert body["is_shadow_enabled"]    is False
        assert body["percent_rollout"]      is None

    def test_reflects_setting_changes(self, client, admin):
        _set(client, admin, "assistant.flow", "percent:25")
        _set(client, admin, "assistant.agentic.tools_max_calls", 6)
        _set(client, admin, "assistant.agentic.router_system",
              "Custom router prompt for testing.")
        _set(client, admin, "assistant.agentic.shadow_sampling_rate", 0.5)

        h = auth_header(client, admin.email)
        body = client.get(
            "/api/v1/admin/assistant-flow/state", headers=h).json()
        assert body["flow"] == "percent:25"
        assert body["tools_max_calls"] == 6
        assert body["router_system"] == "Custom router prompt for testing."
        assert body["shadow_sampling_rate"] == 0.5
        assert body["is_agentic_reachable"] is True
        assert body["percent_rollout"]      == 25

    def test_is_shadow_enabled_requires_both_flow_and_rate(
        self, client, admin,
    ):
        """``is_shadow_enabled`` is a UX hint — true only when the
        admin both set flow=shadow AND a non-zero sampling rate.
        Either one alone is functionally disabled."""
        _set(client, admin, "assistant.flow", "shadow")
        h = auth_header(client, admin.email)
        body = client.get(
            "/api/v1/admin/assistant-flow/state", headers=h).json()
        # flow=shadow but rate=0.0 → shadow effectively disabled.
        assert body["is_shadow_enabled"] is False

        _set(client, admin, "assistant.agentic.shadow_sampling_rate", 0.1)
        body = client.get(
            "/api/v1/admin/assistant-flow/state", headers=h).json()
        assert body["is_shadow_enabled"] is True

    def test_percent_rollout_null_when_flow_not_percent(
        self, client, admin,
    ):
        _set(client, admin, "assistant.flow", "agentic")
        h = auth_header(client, admin.email)
        body = client.get(
            "/api/v1/admin/assistant-flow/state", headers=h).json()
        assert body["percent_rollout"] is None


# ============================================================ /preview

class TestPreview:

    def test_legacy_flow_routes_anyone_to_legacy(self, client, admin):
        h = auth_header(client, admin.email)
        body = client.get(
            "/api/v1/admin/assistant-flow/preview"
            "?as_anon_id=abc-123", headers=h).json()
        assert body["decision"]["primary"] == "legacy"
        assert body["decision"]["shadow"]  is None
        # Cohort bucket is still computed (0..99) so the admin can
        # see "this user is in bucket 47" even on flow=legacy —
        # useful for planning a percent rollout cutover.
        assert 0 <= body["cohort_bucket"] <= 99

    def test_agentic_flow_routes_anyone_to_agentic(self, client, admin):
        _set(client, admin, "assistant.flow", "agentic")
        h = auth_header(client, admin.email)
        body = client.get(
            "/api/v1/admin/assistant-flow/preview"
            "?as_anon_id=xyz", headers=h).json()
        assert body["decision"]["primary"] == "agentic"

    def test_percent_split_is_stable_for_same_identity_within_day(
        self, client, admin,
    ):
        _set(client, admin, "assistant.flow", "percent:50")
        h = auth_header(client, admin.email)
        body1 = client.get(
            "/api/v1/admin/assistant-flow/preview"
            "?as_anon_id=stable-anon", headers=h).json()
        body2 = client.get(
            "/api/v1/admin/assistant-flow/preview"
            "?as_anon_id=stable-anon", headers=h).json()
        # Same identity, same day → identical decision.
        assert body1["decision"] == body2["decision"]
        assert body1["cohort_bucket"] == body2["cohort_bucket"]

    def test_preview_accepts_either_user_id_or_anon_id(self, client, admin):
        h = auth_header(client, admin.email)
        r = client.get(
            "/api/v1/admin/assistant-flow/preview?as_user_id=42",
            headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["as_user_id"] == 42
        assert body["as_anon_id"] is None
        assert "primary" in body["decision"]

    def test_preview_no_identity_falls_through_to_default(
        self, client, admin,
    ):
        """No identity passed → resolver still gives an answer
        (user_id=None, anon_id=None). Useful as a sanity check."""
        h = auth_header(client, admin.email)
        r = client.get(
            "/api/v1/admin/assistant-flow/preview", headers=h)
        assert r.status_code == 200
        body = r.json()
        # Default seed = legacy → anyone routes there.
        assert body["decision"]["primary"] == "legacy"

    def test_shadow_mode_decision_includes_shadow_field(
        self, client, admin,
    ):
        """Under flow=shadow with rate=1.0, the decision exposes
        shadow=agentic so the admin can confirm shadow IS sampling."""
        _set(client, admin, "assistant.flow", "shadow")
        _set(client, admin, "assistant.agentic.shadow_sampling_rate", 1.0)

        h = auth_header(client, admin.email)
        body = client.get(
            "/api/v1/admin/assistant-flow/preview"
            "?as_anon_id=shadow-test", headers=h).json()
        assert body["decision"]["primary"] == "legacy"
        assert body["decision"]["shadow"]  == "agentic"
