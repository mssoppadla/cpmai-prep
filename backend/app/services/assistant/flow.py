"""Orchestration-flow resolver.

Reads ``assistant.flow`` from settings_store and decides — for a given
request — whether to run the LEGACY pipeline (keyword classifier +
per-intent handlers) or the AGENTIC pipeline (router + tool calling +
synthesis).

Modes the setting accepts:
  * ``"legacy"``      — every request runs legacy (default)
  * ``"agentic"``     — every request runs agentic
  * ``"percent:N"``   — N% of requests run agentic, the rest legacy,
                        partitioned deterministically by user identity
  * ``"shadow"``      — legacy runs and is returned to the user; agentic
                        also runs in the background for comparison
                        (sampled by ``assistant.agentic.shadow_sampling_rate``).
                        The resolver tells the orchestrator which side(s)
                        to run; what to RETURN is always the legacy answer
                        in shadow mode.

Two design choices worth knowing:

1. **Daily-rotated cohort hash.** For ``percent:N`` we hash
   ``identity + UTC date`` not ``identity`` alone. The same user lands
   on the same flow for a full UTC day (so they don't see inconsistent
   answers turn-to-turn), but the next day they get re-bucketed. If a
   user happens to be on the "bad" branch one day, tomorrow's fresh
   shot is automatic — no admin intervention needed.

2. **Defence-in-depth fallback.** Even though admin/settings.py
   validates the value at PATCH time, the resolver is paranoid: any
   value it doesn't understand becomes ``LEGACY``. The chat path can
   never be broken by a typo in the admin form.

This module is intentionally tiny + side-effect-free so it's trivial
to unit-test. The actual flow EXECUTION lives in the orchestrator.
"""
from __future__ import annotations

import enum
import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.settings_store import settings_store


class Flow(str, enum.Enum):
    """Concrete flow to execute for a single request."""
    LEGACY  = "legacy"
    AGENTIC = "agentic"


@dataclass(frozen=True)
class FlowDecision:
    """What the orchestrator should actually do for this request.

    Attributes:
      primary:        The flow whose response the user gets back.
                      Always set.
      shadow:         When non-None, ALSO run this flow in the
                      background and log the result for comparison
                      — but don't return it to the user. Used only
                      in shadow mode (and only on the sampled fraction
                      of requests).
      reason:         Short string explaining how the decision was
                      reached. Goes into the audit_log so operators
                      can debug "why did THIS user get THAT flow".
    """
    primary: Flow
    shadow:  Flow | None = None
    reason:  str = "default-legacy"


def resolve_flow(
    *,
    user_id: int | None,
    anon_id: str | None,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> FlowDecision:
    """Decide which flow(s) to run for the current request.

    Args:
      user_id: Authenticated user's ID, if any. Used for cohort hashing.
      anon_id: Anonymous-visitor identifier, if any. Used for cohort
               hashing when user_id is None.
      now:     Override the wall clock for tests (mostly so we can
               assert "same user, different day → different bucket"
               without `freeze_time`).
      rng:     Override the RNG used for shadow sampling. Tests pin
               this to make shadow-mode behaviour deterministic.

    Returns:
      FlowDecision telling the orchestrator which flow to run (and
      whether to also run a shadow flow alongside).

    Falls back to LEGACY on any malformed setting value — chat is
    never broken by an admin typo.
    """
    raw = settings_store.get_str("assistant.flow", "legacy") or "legacy"
    mode = raw.strip().lower()

    if mode == "legacy":
        return FlowDecision(Flow.LEGACY, None, "setting=legacy")

    if mode == "agentic":
        return FlowDecision(Flow.AGENTIC, None, "setting=agentic")

    if mode == "shadow":
        # Returning legacy; conditionally also running agentic in the
        # background. Sampling rate gates the cost — at 0.0 (the seed
        # default) shadow mode is functionally disabled, useful for
        # plumbing the wiring before any real agentic traffic.
        sample = settings_store.get_float(
            "assistant.agentic.shadow_sampling_rate", 0.0)
        sample = _clamp(sample, 0.0, 1.0)
        r = rng or random.Random(_identity_seed(user_id, anon_id, now))
        if r.random() < sample:
            return FlowDecision(
                Flow.LEGACY, Flow.AGENTIC,
                f"shadow sampled (rate={sample:.2f})")
        return FlowDecision(
            Flow.LEGACY, None,
            f"shadow not sampled (rate={sample:.2f})")

    if mode.startswith("percent:"):
        try:
            pct = int(mode.split(":", 1)[1])
        except (ValueError, IndexError):
            return FlowDecision(Flow.LEGACY, None,
                                 f"malformed percent value: {raw!r}")
        pct = _clamp_int(pct, 0, 100)
        bucket = _cohort_bucket(user_id, anon_id, now)
        if bucket < pct:
            return FlowDecision(
                Flow.AGENTIC, None,
                f"percent:{pct} hit (bucket={bucket})")
        return FlowDecision(
            Flow.LEGACY, None,
            f"percent:{pct} miss (bucket={bucket})")

    # Unknown / malformed — safest behaviour is to stay on legacy. The
    # admin validator should have caught this, so reaching here is a
    # belt-and-braces guard against future seed bugs.
    return FlowDecision(Flow.LEGACY, None, f"unknown flow value: {raw!r}")


# --------------------------------------------------------------- helpers

def _identity_seed(
    user_id: int | None,
    anon_id: str | None,
    now: datetime | None,
) -> int:
    """Stable seed combining identity + UTC date.

    Used for shadow-mode sampling and (indirectly via _cohort_bucket)
    for percent-rollout bucketing. SHA-256 because Python's built-in
    hash() is randomised per process — we need cross-process
    determinism so two workers behind the same load balancer give the
    same user the same flow.
    """
    ident = f"u{user_id}" if user_id is not None else f"a{anon_id or ''}"
    day = (now or datetime.now(timezone.utc)).strftime("%Y%m%d")
    digest = hashlib.sha256(f"{ident}|{day}".encode("utf-8")).digest()
    # First 8 bytes is plenty; int.from_bytes returns a non-negative int.
    return int.from_bytes(digest[:8], "big", signed=False)


def _cohort_bucket(
    user_id: int | None,
    anon_id: str | None,
    now: datetime | None,
) -> int:
    """Stable 0..99 bucket for percent-rollout.

    ``flow="percent:N"`` means: if bucket < N, run agentic. So a
    user in bucket 7 sees agentic at percent:10 and above; a user in
    bucket 73 only sees it at percent:74+.

    Re-bucketed daily — see module docstring for rationale.
    """
    return _identity_seed(user_id, anon_id, now) % 100


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _clamp_int(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))
