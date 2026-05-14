"""Assistant orchestrator: classify intent → route to handler → guardrail output.

Top-level entry point is :meth:`AssistantOrchestrator.handle`, which
guardrails the input/output and runs ONE of two orchestration flows
based on the ``assistant.flow`` setting (resolved per-request via
:mod:`app.services.assistant.flow`):

  * **legacy**  — the keyword-classifier + per-intent handler pipeline
                  documented in this file's class body. Default and only
                  fully-implemented flow today.
  * **agentic** — LangGraph-style router + tool-calling + synthesis.
                  Currently a placeholder (raises NotImplementedError).
                  The agentic implementation lands in a follow-up PR;
                  the foundation here is the settings + flow resolver +
                  the dispatch branch that flips between them.

Why land the dispatch branch BEFORE the agentic impl: it lets us ship
the setting (and admin-validate it, and seed it as "legacy") without
risk of any user actually triggering the unfinished code path. Once
agentic implementation lands, operators flip the setting and traffic
moves over with no further deploy.
"""
import structlog
from sqlalchemy.orm import Session
from app.utils.pii import redact
from app.models.assistant_log import AssistantLog
from app.models.user import User
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.services.assistant.drift import DriftContext, detect_and_log
from app.services.assistant.flow import Flow, FlowDecision, resolve_flow
from app.services.assistant.guardrails import AssistantGuardrails
from app.services.assistant.intent_classifier import IntentClassifier, Intent
from app.services.assistant.llm_registry import LLMRegistry
from app.services.assistant.handlers.account_handler import AccountHandler
from app.services.assistant.handlers.faq_handler import FAQHandler
from app.services.assistant.handlers.content_handler import ContentHandler
from app.services.assistant.handlers.insights_handler import InsightsHandler
from app.services.assistant.handlers.pmi_handler import PmiReferenceHandler

log = structlog.get_logger("assistant.orchestrator")


# Maps Intent → handler.name (matches the handler classes' .name
# attributes, used as the settings-key segment for configurable
# system prompts AND as the drift-context handler discriminator).
# PMI_REFERENCE has no LLM call so it's not a drift-detection target.
_INTENT_TO_HANDLER_NAME = {
    Intent.ACCOUNT:        "account",
    Intent.FAQ:            "faq",
    Intent.CONTENT:        "content",
    Intent.INSIGHTS:       "insights",
    Intent.PMI_REFERENCE:  "pmi_reference",
}


class AssistantOrchestrator:
    def __init__(self, db: Session):
        self.db = db
        self.guardrails = AssistantGuardrails()
        self.classifier = IntentClassifier()

    def handle(self, request: AssistantRequest, user: User | None
               ) -> AssistantResponse:
        # Input guardrails are layer-zero — they run before BOTH flows
        # (regex injection check, length cap, Redis cooldown).
        safe_msg = self.guardrails.check_input(
            request.message, user_id=request.user_id, anon_id=request.anon_id,
        )

        # Decide flow per-request. Default + every-fallback is legacy;
        # the orchestrator can never get stuck on a broken agentic
        # branch due to a bad setting value.
        decision = resolve_flow(
            user_id=user.id if user else None,
            anon_id=request.anon_id,
        )

        if decision.primary is Flow.LEGACY:
            return self._handle_legacy(request, user, safe_msg, decision)

        # Agentic path — implementation lands in the follow-up PR. The
        # raise here is intentional: we want the foundation (settings +
        # resolver + dispatch) to be reviewable and tested before the
        # router/tools/synthesis code arrives. With the seed default
        # of "legacy", no real request ever reaches this branch on prod
        # until an admin opts in.
        raise NotImplementedError(
            "Agentic flow is not yet wired in. Set assistant.flow=legacy "
            "to disable (this is also the seed default). The agentic "
            "implementation lands in a follow-up PR.")

    # ------------------------------------------------------------ legacy
    def _handle_legacy(
        self,
        request: AssistantRequest,
        user: User | None,
        safe_msg: str,
        decision: FlowDecision,
    ) -> AssistantResponse:
        """Original keyword-classifier + per-intent-handler pipeline.

        Identical in behaviour to the pre-refactor ``handle()`` body —
        kept byte-for-byte equivalent except for the ``flow=`` value
        passed to the drift detector (now sourced from the FlowDecision
        rather than hard-coded). Regression test in
        ``test_orchestrator_flow_dispatch.py`` pins this contract.
        """
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

        # Drift detection — runs against the LLM's response + retrieval
        # state. Writes structured audit_log rows for signatures the
        # operator can act on (refused-with-context, missing-citation,
        # etc.). No-op when assistant.drift_detection_enabled is false
        # (default during initial rollout). Wrapped in try/except so a
        # detector bug can never break a chat turn.
        try:
            detect_and_log(self.db, DriftContext(
                user_id=user.id if user else None,
                flow=decision.primary.value,   # "legacy" or "agentic"
                handler=_INTENT_TO_HANDLER_NAME.get(intent, intent.value),
                intent=intent.value,
                question=safe_msg,
                response=safe_out,
                # len(citations) is a reliable proxy for "how many chunks
                # were available" — to_citations is 1:1 with retrieved
                # chunks, no filtering. Saves us from plumbing chunk
                # lists out of every handler.
                retrieval_count=len(raw.get("citations", []) or []),
            ))
        except Exception:
            log.exception("assistant.drift_detection_crashed")

        # Log redacted version. Return the log row's id so the frontend
        # can reference this specific turn when the user clicks "Wasn't
        # helpful" → POST /assistant/turns/{log_id}/flag.
        log_row = AssistantLog(
            user_id=user.id if user else None,
            anon_id=request.anon_id,
            intent=intent.value, intent_confidence=confidence,
            provider=provider.name, model=getattr(provider, "model", None),
            redacted_input=redact(safe_msg)[:2000],
            response_preview=safe_out[:500],
        )
        self.db.add(log_row)
        self.db.commit()
        self.db.refresh(log_row)

        return AssistantResponse(
            turn_id=log_row.id,
            intent=intent.value, intent_confidence=confidence,
            message=safe_out,
            citations=raw.get("citations", []),
            suggested_actions=raw.get("suggested_actions", []),
            provider=provider.name,
            model_version=getattr(provider, "model", None),
        )
