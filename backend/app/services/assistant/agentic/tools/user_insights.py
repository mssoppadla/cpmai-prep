"""user_insights tool — read the signed-in user's recent exam attempts.

NO LLM call. Pure DB lookup on ``exam_sessions``. Returns the last 5
submitted attempts as a structured summary that synthesis can use to
give personalised feedback:

    Recent exam attempts (last 5, newest first):
      Set 14 · 72% · passed (12 min)
      Set 11 · 58% · failed (15 min)
      ...

Mirrors the legacy InsightsHandler's data path. Refuses anonymous
users.
"""
from __future__ import annotations

from typing import Any

from app.models.exam_session import ExamSession
from app.services.assistant.agentic.registry import register
from app.services.assistant.agentic.types import (
    Tool, ToolContext, ToolResult, ToolStatus,
)


class UserInsightsTool(Tool):
    name = "user_insights"
    description = (
        "Read the SIGNED-IN user's recent CPMAI exam attempts (last "
        "5 submitted, newest first). Use this for 'how am I doing', "
        "'what should I improve', 'my last exam score', 'am I ready "
        "for the exam' kinds of questions. Refuses for anonymous "
        "users."
    )
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},   # identity comes from ToolContext
    }
    requires_user = True
    has_llm_call  = False

    def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if ctx.user is None:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.REFUSED_NEED_AUTH,
                content=(
                    "Exam-attempt insights require sign-in. Ask the "
                    "user to sign in, then retry."
                ),
                error="anonymous_user",
            )
        try:
            sessions = (
                ctx.db.query(ExamSession)
                .filter_by(user_id=ctx.user.id, status="submitted")
                .order_by(ExamSession.submitted_at.desc())
                .limit(5)
                .all()
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                error=f"db lookup failed: {e}",
            )

        if not sessions:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.OK,
                content=(
                    f"User {ctx.user.email} has no submitted exam "
                    "attempts yet. Suggest they take a Mock Exam so "
                    "we can give targeted advice."
                ),
                suggested_actions=[
                    {"label": "Browse exam sets", "url": "/exams"},
                ],
                metadata={"attempts_count": 0},
            )

        lines = [
            f"Recent CPMAI exam attempts for {ctx.user.email} "
            f"(last {len(sessions)}, newest first):"
        ]
        for s in sessions:
            verdict = ("passed" if s.passed
                        else "failed" if s.passed is False
                        else "unknown")
            time_part = (f" ({s.time_taken_seconds // 60} min)"
                          if s.time_taken_seconds else "")
            lines.append(
                f"  Set {s.exam_set_id} · "
                f"{s.score if s.score is not None else '?'}% · "
                f"{verdict}{time_part}"
            )

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.OK,
            content="\n".join(lines),
            metadata={
                "attempts_count": len(sessions),
                "latest_score": sessions[0].score,
                "latest_passed": sessions[0].passed,
            },
        )


register(UserInsightsTool())
