"""Admin control plane for the assistant.flow toggle.

The toggle itself is just a settings_store key (``assistant.flow``)
that operators can edit via the generic ``/admin/settings`` page.
This module adds two affordances on top of that raw control surface:

  * ``GET /admin/assistant-flow/state`` — one round-trip read of the
    current flow setting AND every related agentic-config key, so the
    dedicated admin page can render its form without N PATCH-shaped
    /admin/settings GETs.

  * ``GET /admin/assistant-flow/preview?as_anon_id=...`` — show which
    flow a given identity would land on RIGHT NOW given the current
    setting + cohort hashing. Lets an admin verify "yes, this anon
    user really is in the agentic 10% cohort today" before flipping
    a percentage rollout to a wider bucket.

Both endpoints are admin-gated by the parent router. Read-only by
design; updates go through the existing ``/admin/settings`` PATCH
endpoint that already enforces per-key validation.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_admin_user, get_db
from app.core.settings_store import settings_store
from app.models.user import User
from app.services.assistant.flow import (
    Flow, FlowDecision, _cohort_bucket, resolve_flow,
)

router = APIRouter()


# Keys this dashboard cares about. Listed centrally so both endpoints
# and any future test fixture can iterate without duplication.
_FLOW_KEYS = (
    "assistant.flow",
    "assistant.agentic.tools_max_calls",
    "assistant.agentic.router_system",
    "assistant.agentic.synthesis_system",
    "assistant.agentic.shadow_sampling_rate",
)


@router.get("/state")
def assistant_flow_state(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
) -> dict[str, Any]:
    """Return the current flow setting + all agentic-config values.

    Response shape::

      {
        "flow": "percent:10",
        "tools_max_calls": 4,
        "router_system": "",
        "synthesis_system": "",
        "shadow_sampling_rate": 0.0,
        // computed conveniences:
        "is_agentic_reachable": true,    // flow != legacy
        "is_shadow_enabled":    false,   // flow == shadow and rate > 0
        "percent_rollout":      10        // null when flow != percent:N
      }

    The frontend renders form controls keyed on these values; ``Save``
    PATCHes ``/admin/settings/{key}`` individually for each change.
    Keeping the write-path on the existing settings endpoint reuses
    its per-key validator + audit trail without duplicating logic.
    """
    flow_raw = (settings_store.get_str("assistant.flow", "legacy")
                or "legacy").strip().lower()
    tools_max_calls = settings_store.get_int(
        "assistant.agentic.tools_max_calls", 4)
    router_system = settings_store.get_str(
        "assistant.agentic.router_system", "")
    synthesis_system = settings_store.get_str(
        "assistant.agentic.synthesis_system", "")
    shadow_rate = settings_store.get_float(
        "assistant.agentic.shadow_sampling_rate", 0.0)

    percent_rollout: int | None = None
    if flow_raw.startswith("percent:"):
        try:
            percent_rollout = int(flow_raw.split(":", 1)[1])
        except (ValueError, IndexError):
            percent_rollout = None

    return {
        "flow": flow_raw,
        "tools_max_calls": tools_max_calls,
        "router_system": router_system,
        "synthesis_system": synthesis_system,
        "shadow_sampling_rate": shadow_rate,
        # Computed flags — let the frontend render conditional controls
        # without re-implementing the parsing logic.
        "is_agentic_reachable": flow_raw != "legacy",
        "is_shadow_enabled":    flow_raw == "shadow" and shadow_rate > 0,
        "percent_rollout":      percent_rollout,
    }


@router.get("/preview")
def assistant_flow_preview(
    as_user_id: int | None = Query(
        None, description=("Resolve as if this user_id was making the "
                            "request. Defaults to no user (anonymous).")),
    as_anon_id: str | None = Query(
        None, description=("Resolve as if this anon_id was making the "
                            "request. Use this to preview which cohort "
                            "a representative anon visitor would land "
                            "in.")),
    _admin: User = Depends(get_admin_user),
) -> dict[str, Any]:
    """Show which flow a given identity lands on for the CURRENT setting.

    Useful when adjusting percent-rollout cohorts: an admin can paste
    in a real anon_id from /admin/leads's Anonymous Traffic widget and
    confirm "yes, this user is on the agentic side today".

    Note that the answer can change daily — the cohort hash includes
    UTC date — so this is a snapshot, not a guarantee. Identities that
    land on a given flow today may flip tomorrow.

    Response shape::

      {
        "as_user_id": null,
        "as_anon_id": "abc-123",
        "decision": {
          "primary":  "agentic",
          "shadow":   null,
          "reason":   "percent:10 hit (bucket=4)"
        },
        "cohort_bucket": 4    // 0..99; helpful for understanding the
                              // decision when percent rollout is on
      }
    """
    decision: FlowDecision = resolve_flow(
        user_id=as_user_id, anon_id=as_anon_id)
    bucket = _cohort_bucket(user_id=as_user_id, anon_id=as_anon_id, now=None)
    return {
        "as_user_id": as_user_id,
        "as_anon_id": as_anon_id,
        "decision": {
            "primary": decision.primary.value,
            "shadow":  decision.shadow.value if decision.shadow else None,
            "reason":  decision.reason,
        },
        "cohort_bucket": bucket,
    }
