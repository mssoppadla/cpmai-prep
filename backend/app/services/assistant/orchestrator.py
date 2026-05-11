"""Assistant orchestrator: classify intent → route to handler → guardrail output."""
import structlog
from sqlalchemy.orm import Session
from app.utils.pii import redact
from app.models.assistant_log import AssistantLog
from app.models.user import User
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.services.assistant.guardrails import AssistantGuardrails
from app.services.assistant.intent_classifier import IntentClassifier, Intent
from app.services.assistant.llm_registry import LLMRegistry
from app.services.assistant.handlers.account_handler import AccountHandler
from app.services.assistant.handlers.faq_handler import FAQHandler
from app.services.assistant.handlers.content_handler import ContentHandler
from app.services.assistant.handlers.insights_handler import InsightsHandler
from app.services.assistant.handlers.pmi_handler import PmiReferenceHandler

log = structlog.get_logger("assistant.orchestrator")


class AssistantOrchestrator:
    def __init__(self, db: Session):
        self.db = db
        self.guardrails = AssistantGuardrails()
        self.classifier = IntentClassifier()

    def handle(self, request: AssistantRequest, user: User | None
               ) -> AssistantResponse:
        safe_msg = self.guardrails.check_input(
            request.message, user_id=request.user_id, anon_id=request.anon_id,
        )
        intent, confidence = self.classifier.classify(safe_msg, request.history)
        provider = LLMRegistry.get_active()

        handlers = {
            Intent.ACCOUNT:        AccountHandler,
            Intent.FAQ:            FAQHandler,
            Intent.CONTENT:        ContentHandler,
            Intent.INSIGHTS:       InsightsHandler,
            Intent.PMI_REFERENCE:  PmiReferenceHandler,
        }
        handler = handlers[intent](self.db, provider)
        try:
            raw = handler.respond(request, user)
        except Exception as e:
            log.exception("assistant.handler_failed", intent=intent.value, error=str(e))
            raw = {"message": "Sorry, I hit an error. Please try again.",
                   "citations": [], "suggested_actions": []}

        safe_out = self.guardrails.check_output(raw["message"])

        # Log redacted version
        self.db.add(AssistantLog(
            user_id=user.id if user else None,
            anon_id=request.anon_id,
            intent=intent.value, intent_confidence=confidence,
            provider=provider.name, model=getattr(provider, "model", None),
            redacted_input=redact(safe_msg)[:2000],
            response_preview=safe_out[:500],
        ))
        self.db.commit()

        return AssistantResponse(
            intent=intent.value, intent_confidence=confidence,
            message=safe_out,
            citations=raw.get("citations", []),
            suggested_actions=raw.get("suggested_actions", []),
            provider=provider.name,
            model_version=getattr(provider, "model", None),
        )
