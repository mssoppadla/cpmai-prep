"""human_escalation tool — log a "talk to a human" request as a lead.

NO LLM call. Pure DB insert into ``leads`` with
``source=LeadSource.CHAT_CALLBACK`` (the same source the existing
"Talk to a human" widget button uses, so admin /admin/leads shows
both flows together without UI changes).

The router picks this when the user clearly wants a human (or when
synthesis decided every other tool returned nothing useful). It
records:

  * ``reason``        — short LLM-generated description of why
                        escalation was chosen (synth quality
                        signal)
  * ``phone``         — optional, if the user typed one in chat
  * ``note``          — optional free-text the user added

For SIGNED-IN users we use their account email; for anonymous users
the tool refuses — escalation needs a contact channel. Operators
later reach out via the email/phone on the admin/leads page.
"""
from __future__ import annotations

from typing import Any

from app.models.lead import Lead, LeadSource
from app.services.assistant.agentic.registry import register
from app.services.assistant.agentic.types import (
    Tool, ToolContext, ToolResult, ToolStatus,
)


# Max char cap matches the existing leads.submit endpoint's
# interests-entry cap (200 chars) — same operational guard against
# someone smuggling 50KB of text into a single lead row.
_MAX_NOTE_LEN = 200
_MAX_REASON_LEN = 200


class HumanEscalationTool(Tool):
    name = "human_escalation"
    description = (
        "Log an escalation request — the user wants a human to "
        "follow up. Use this when the user explicitly asks for a "
        "human, asks for a callback, or when no other tool can "
        "answer their question and a human review would help. "
        "Requires a signed-in user (we need a contact email). The "
        "operator will see this in the /admin/leads dashboard."
    )
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "1-2 sentence summary of WHY this is being "
                    "escalated. E.g. 'user explicitly asked for "
                    "callback', 'pricing question wasn't covered "
                    "by knowledge base'. Helps the operator triage."
                ),
            },
            "phone": {
                "type": "string",
                "description": (
                    "Optional phone number the user provided in "
                    "chat. Empty/null if they didn't share one."
                ),
            },
            "note": {
                "type": "string",
                "description": (
                    "Optional additional context the user wants "
                    "the operator to know — e.g. timezone, best "
                    "time to call, topic."
                ),
            },
        },
        "required": ["reason"],
    }
    requires_user = True
    has_llm_call  = False

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if ctx.user is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.REFUSED_NEED_AUTH,
                content=(
                    "Escalation requires a signed-in user (we need a "
                    "contact email). Tell the user to sign in first."
                ),
                error="anonymous_user",
            )

        reason = (args.get("reason") or "").strip()[:_MAX_REASON_LEN]
        phone  = (args.get("phone") or "").strip() or None
        note   = (args.get("note") or "").strip()[:_MAX_NOTE_LEN] or None

        if not reason:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                error="reason is required",
            )

        # Build the lead row using the same column shape the existing
        # chat-callback flow uses. The `interests` JSON column holds
        # the reason + optional note as a free-form list — that's the
        # convention the admin /leads page already renders.
        interests: list[str] = [f"agentic-escalation: {reason}"]
        if note:
            interests.append(note)

        try:
            row = Lead(
                email=ctx.user.email,
                name=ctx.user.name,
                phone=phone,
                source=LeadSource.CHAT_CALLBACK,
                interests=interests,
                consent_marketing=False,
            )
            ctx.db.add(row)
            ctx.db.commit()
            ctx.db.refresh(row)
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                error=f"lead insert failed: {e}",
            )

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.OK,
            content=(
                "Escalation logged. The operations team will reach "
                "out on the user's account email within one business "
                "day."
            ),
            metadata={
                "lead_id": row.id,
                "phone_provided": bool(phone),
                "note_provided":  bool(note),
            },
        )


register(HumanEscalationTool())
