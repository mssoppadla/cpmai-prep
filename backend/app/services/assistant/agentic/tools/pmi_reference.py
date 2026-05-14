"""pmi_reference tool — return the official PMI link for the topic.

NO LLM call. Pure ``settings_store`` lookup against:

  * ``pmi.course_bundle_url`` — registration / exam fees / scheduling
  * ``pmi.eco_url``           — Exam Content Outline (syllabus)

The router picks ``intent`` so the tool can surface the right URL
without re-parsing the user's question. Falls back to a generic
"search PMI.org" message if the requested URL isn't configured.

Equivalent to the legacy PmiReferenceHandler. NO LLM call, NO
embedding call — the cheapest tool in the registry.
"""
from __future__ import annotations

from typing import Any

from app.core.settings_store import settings_store
from app.services.assistant.agentic.registry import register
from app.services.assistant.agentic.types import (
    Tool, ToolContext, ToolResult, ToolStatus,
)


# Intent → (setting_key, title, body). Tuned to match the legacy
# handler's responses so users see identical text whichever flow
# runs. Adding a third intent (say "renewal") is one row + a new
# pmi.* setting.
_INTENT_TO_RESPONSE: dict[str, tuple[str, str, str]] = {
    "eco": (
        "pmi.eco_url",
        "Official CPMAI Exam Content Outline",
        ("PMI publishes the canonical Exam Content Outline (ECO) "
         "for the CPMAI certification — every domain, task, and "
         "enabler the exam can test against. It's the single source "
         "of truth for what's covered."),
    ),
    "course": (
        "pmi.course_bundle_url",
        "CPMAI Course Bundle on PMI",
        ("CPMAI registration and the official course bundle are "
         "managed by PMI directly. You'll find pricing, registration "
         "steps, and exam scheduling on their page."),
    ),
}


class PmiReferenceTool(Tool):
    name = "pmi_reference"
    description = (
        "Return a link to PMI's official CPMAI page. Pick "
        "intent='eco' for syllabus / exam-content / 'what's on the "
        "exam' questions; pick intent='course' for registration / "
        "exam fee / course bundle / scheduling questions. NO content "
        "is generated — only an authoritative URL + framing text."
    )
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["eco", "course"],
                "description": (
                    "Which official page to return — 'eco' (Exam "
                    "Content Outline) for syllabus questions, "
                    "'course' (Course Bundle page) for registration "
                    "or fee questions."
                ),
            },
        },
        "required": ["intent"],
    }
    requires_user = False
    has_llm_call  = False

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        intent = (args.get("intent") or "").strip().lower()
        if intent not in _INTENT_TO_RESPONSE:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                error=f"unknown intent: {intent!r}",
            )
        setting_key, title, body = _INTENT_TO_RESPONSE[intent]
        url = settings_store.get_str(setting_key, "")
        if not url:
            # Setting blank — admin hasn't configured this URL yet.
            # Synthesis should NOT invent a URL; return a no-link
            # status and let the LLM mention "search pmi.org".
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.EMPTY,
                content=(
                    f"No '{setting_key}' configured. Tell the user to "
                    "search 'CPMAI' on pmi.org for the latest "
                    "registration page."
                ),
                metadata={"intent": intent, "setting_key": setting_key},
            )

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.OK,
            content=f"{body}\n\nOfficial link: {url}",
            citations=[{"source": "PMI", "title": title, "url": url}],
            suggested_actions=[{"label": title, "url": url}],
            metadata={"intent": intent, "url": url},
        )


register(PmiReferenceTool())
