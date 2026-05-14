"""Personalized insights based on the user's exam history."""
from app.services.assistant.providers.base import LLMProvider
from app.models.exam_session import ExamSession
from app.services.assistant.system_prompt import configurable_handler_system


# Hardcoded fallback — used when assistant.handler.insights.system is empty.
DEFAULT_SYSTEM = (
    "You analyze a learner's CPMAI exam attempts and give actionable, encouraging "
    "feedback. Stay grounded in the data provided."
)


class InsightsHandler:
    name = "insights"

    def __init__(self, db, provider: LLMProvider):
        self.db = db
        self.provider = provider

    def respond(self, request, user) -> dict:
        if not user:
            return {
                "message": "Sign in so I can review your attempts and give personalized advice.",
                "citations": [], "suggested_actions": ["Sign in"],
            }
        sessions = (self.db.query(ExamSession)
                    .filter_by(user_id=user.id, status="submitted")
                    .order_by(ExamSession.submitted_at.desc()).limit(5).all())
        if not sessions:
            return {
                "message": "I don't see any submitted exam attempts yet. "
                           "Take a Mock Exam first and I can give targeted advice.",
                "citations": [], "suggested_actions": ["Browse exam sets"],
            }
        summary = "\n".join(
            f"- Set {s.exam_set_id} · score {s.score}% · {'passed' if s.passed else 'failed'}"
            for s in sessions
        )
        system = configurable_handler_system(self.name, DEFAULT_SYSTEM)
        history = [
            {"role": "system", "content": f"Recent attempts:\n{summary}"},
            {"role": "user", "content": request.message},
        ]
        return {"message": self.provider.complete(system, history),
                "citations": [], "suggested_actions": []}
