"""account_state tool — read the signed-in user's subscription state.

NO LLM call. Pure DB lookup on ``users`` + ``subscriptions``. Returns
a one-paragraph summary the synthesis LLM can read directly:

    "User has an ACTIVE 'pro' subscription. Period: 2026-04-01 →
    2026-07-01. Expires: 2026-07-01."

The router picks this tool for "what's my subscription / when does
my plan expire / am I still paid up" kinds of questions. Refuses
anonymous users with ToolStatus.REFUSED_NEED_AUTH — the orchestrator
surfaces a "please sign in" message instead of inventing data.

We deliberately keep the output **opaque to the synthesis LLM** —
no PII beyond what's already in the user's session, no other-user
data, no payment methods or card tails.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.subscription import Subscription
from app.services.assistant.agentic.registry import register
from app.services.assistant.agentic.types import (
    Tool, ToolContext, ToolResult, ToolStatus,
)


class AccountStateTool(Tool):
    name = "account_state"
    description = (
        "Read the SIGNED-IN user's current subscription state — plan "
        "name, status (active/cancelled/expired), current period, and "
        "expiry. Use this for 'what's my plan', 'when does my "
        "subscription expire', 'am I still paid up' questions. "
        "Refuses for anonymous users; the synthesis step should "
        "prompt them to sign in if this tool returns "
        "REFUSED_NEED_AUTH."
    )
    parameters_schema: dict[str, Any] = {
        # No args — the user identity comes from ToolContext.
        "type": "object",
        "properties": {},
    }
    requires_user = True
    has_llm_call  = False

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if ctx.user is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.REFUSED_NEED_AUTH,
                content=(
                    "Account-state queries require sign-in. Ask the user "
                    "to sign in, then retry."
                ),
                error="anonymous_user",
            )
        try:
            sub = (ctx.db.query(Subscription)
                    .filter(Subscription.user_id == ctx.user.id)
                    .order_by(Subscription.created_at.desc())
                    .first())
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                error=f"db lookup failed: {e}",
            )

        if sub is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.OK,
                content=(
                    f"User {ctx.user.email} has no subscription rows. "
                    "They are on the free tier."
                ),
                metadata={"has_subscription": False},
            )

        # Active iff status='active' AND (no expires_at OR expires_at > now).
        # Same logic the paywall enforces — keep them aligned.
        now = datetime.now(timezone.utc)
        is_active = (sub.status == "active"
                      and (sub.expires_at is None
                           or sub.expires_at > now))

        lines = [
            f"User {ctx.user.email} subscription:",
            f"  plan:         {sub.plan or '(unnamed)'}",
            f"  status:       {sub.status}",
            f"  paywall_view: {'ACTIVE' if is_active else 'INACTIVE'}",
        ]
        if sub.current_period_start:
            lines.append(
                f"  period_start: {sub.current_period_start.isoformat()}")
        if sub.current_period_end:
            lines.append(
                f"  period_end:   {sub.current_period_end.isoformat()}")
        if sub.expires_at:
            lines.append(f"  expires_at:   {sub.expires_at.isoformat()}")
        if sub.cancelled_at:
            lines.append(f"  cancelled_at: {sub.cancelled_at.isoformat()}")

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.OK,
            content="\n".join(lines),
            metadata={
                "has_subscription": True,
                "is_active": is_active,
                "plan": sub.plan,
                "status": sub.status,
            },
        )


register(AccountStateTool())
