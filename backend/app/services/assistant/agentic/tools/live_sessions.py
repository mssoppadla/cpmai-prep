"""live_sessions tool — upcoming live class schedule, straight from the DB.

NO LLM call. Reads ``zoom_sessions`` live so dates are NEVER stale
(the RAG ``zoom_session`` corpus covers the legacy flow, but a corpus
is only as fresh as its last reindex — schedule questions deserve the
real rows). Public-safe by design:

  * anonymous users allowed — session titles + dates are marketing
    info (the landing banner advertises live classes to everyone)
  * NEVER exposes zoom_join_url / zoom_start_url / meeting ids
  * joining still requires enrolment/subscription — the summary says
    so, and the suggested action points at the admin-configured
    registration link (landing.live_banner_link_url) when set

Router picks this for "when is the next live class / session /
webinar", "live class schedule", "what time is Saturday's class".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.settings_store import settings_store
from app.models.lms import Course
from app.models.zoom import ZoomSession
from app.services.assistant.agentic.registry import register
from app.services.assistant.agentic.types import (
    Tool, ToolContext, ToolResult, ToolStatus,
)

_MAX_SESSIONS = 8


class LiveSessionsTool(Tool):
    name = "live_sessions"
    description = (
        "List UPCOMING live class sessions (Zoom) with their scheduled "
        "dates, times (UTC), durations, and linked course. Use for "
        "'when is the next live class/session/webinar', 'live class "
        "schedule', 'what time is the class on <day>'. Works for "
        "anonymous users; never returns join links."
    )
    parameters_schema: dict[str, Any] = {
        # No args — always returns the upcoming schedule.
        "type": "object",
        "properties": {},
    }
    requires_user = False
    has_llm_call  = False

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        now = datetime.now(timezone.utc)
        try:
            rows = (ctx.db.query(ZoomSession)
                    .filter(ZoomSession.status.in_(("scheduled", "live")),
                            ZoomSession.is_deleted.is_(False),
                            # Grace window: a session that started up to
                            # 3h ago may still be running even if the
                            # status webhook lagged.
                            ZoomSession.scheduled_at >= now - timedelta(hours=3))
                    .order_by(ZoomSession.scheduled_at)
                    .limit(_MAX_SESSIONS)
                    .all())
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                error=f"db lookup failed: {e}",
            )

        register_url = settings_store.get_str(
            "landing.live_banner_link_url", "")
        actions = ([{"label": "Register for live classes",
                     "url": register_url}] if register_url else [])

        if not rows:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.OK,
                content=(
                    "No upcoming live class sessions are scheduled right "
                    "now. New sessions are announced on the site."
                ),
                suggested_actions=actions,
                metadata={"session_count": 0},
            )

        course_titles: dict[int, str] = {}
        course_ids = {r.course_id for r in rows if r.course_id}
        if course_ids:
            for c in (ctx.db.query(Course)
                      .filter(Course.id.in_(course_ids)).all()):
                course_titles[c.id] = c.title

        lines = ["Upcoming live class sessions (all times UTC):"]
        for r in rows:
            when = r.scheduled_at
            if when is not None and when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            when_text = (when.strftime("%A %d %B %Y, %H:%M UTC")
                         if when else "date TBA")
            line = (f"  - {r.title} — {when_text} "
                    f"({r.duration_minutes} min, status: {r.status})")
            if r.course_id and r.course_id in course_titles:
                line += f" — part of course: {course_titles[r.course_id]}"
            lines.append(line)
        lines.append(
            "Joining requires an enrolled or subscribed account (join "
            "links appear on the signed-in dashboard). Do not invent "
            "join URLs.")

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.OK,
            content="\n".join(lines),
            suggested_actions=actions,
            metadata={"session_count": len(rows)},
        )


register(LiveSessionsTool())
