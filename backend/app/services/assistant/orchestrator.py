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
import time
import structlog
from sqlalchemy.orm import Session
from app.core.audit import audit_log
from app.utils.pii import redact
from app.models.assistant_log import AssistantLog
from app.models.user import User
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.services.assistant.agentic.orchestrator import AgenticOrchestrator
# Import the tools package for its side-effect: each module's
# import-time register(...) call populates the agentic registry.
# Without this import, AgenticOrchestrator sees zero tools.
from app.services.assistant.agentic import tools as _agentic_tools_pkg  # noqa: F401
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
            response = self._handle_legacy(request, user, safe_msg, decision)
        else:
            response = self._handle_agentic(request, user, safe_msg, decision)

        # Shadow execution — synchronous + no-raise. The shadow side
        # runs only when ``decision.shadow`` is set (which happens
        # only in ``flow=shadow`` mode AND only when the per-request
        # sampling roll fired). It logs to audit_log + the drift
        # detector under a distinct flow discriminator so dashboards
        # can compare side-by-side; it does NOT influence the response
        # we return.
        if decision.shadow is not None:
            self._run_shadow(request, user, safe_msg, decision)

        return response

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

    # ----------------------------------------------------------- agentic
    def _handle_agentic(
        self,
        request: AssistantRequest,
        user: User | None,
        safe_msg: str,
        decision: FlowDecision,
    ) -> AssistantResponse:
        """LangGraph-style flow: router → tools → synthesis.

        Wraps :class:`AgenticOrchestrator` with the same audit /
        drift / guardrail machinery the legacy path uses, so the
        response shape (AssistantResponse), drift events, and
        AssistantLog rows are flow-agnostic. The frontend doesn't
        know — or care — which flow ran.
        """
        provider = LLMRegistry.get_active()
        agentic = AgenticOrchestrator(self.db, provider)

        try:
            result = agentic.handle(request, user, request.anon_id)
        except Exception as e:
            log.exception("assistant.agentic_failed", error=str(e))
            # Belt-and-braces: AgenticOrchestrator is contractually
            # no-raise (catches its own errors). If it ever does
            # raise, the chat path still answers something.
            result = _agentic_error_result(str(e))

        safe_out = self.guardrails.check_output(result.message)

        # Drift detection — same rules as legacy, but the discriminator
        # column reads "agentic". The dashboard splits panes on this.
        # ``handler`` becomes a comma-joined list of tools the router
        # picked, so operators can see WHICH tools were involved in a
        # drifted answer.
        try:
            tools_summary = ",".join(
                t.get("name", "?") for t in (result.tools_called or [])
            ) or "(no tools)"
            detect_and_log(self.db, DriftContext(
                user_id=user.id if user else None,
                flow=decision.primary.value,           # "agentic"
                handler=tools_summary,
                # No keyword classifier ran. We pass None so the
                # dashboard's "intent" column reads as empty for
                # agentic rows — they're aggregated by tool list
                # instead.
                intent=None,
                question=safe_msg,
                response=safe_out,
                retrieval_count=len(result.citations or []),
            ))
        except Exception:
            log.exception("assistant.drift_detection_crashed")

        # Per-turn log row. We store the tool-call summary in the
        # response_preview's metadata field via a JSON-encoded
        # extension... wait, there's no metadata column on
        # AssistantLog today. Use intent="agentic" + the existing
        # response_preview to surface what happened; the audit_log
        # drift rows have the full tools_called list.
        log_row = AssistantLog(
            user_id=user.id if user else None,
            anon_id=request.anon_id,
            # We don't have a keyword intent for agentic — use the
            # literal "agentic" so the existing AssistantLog index
            # by intent works as a "which flow ran" filter for
            # quick admin queries.
            intent="agentic",
            intent_confidence=1.0,
            provider=provider.name,
            model=getattr(provider, "model", None),
            redacted_input=redact(safe_msg)[:2000],
            response_preview=safe_out[:500],
        )
        self.db.add(log_row)
        self.db.commit()
        self.db.refresh(log_row)

        return AssistantResponse(
            turn_id=log_row.id,
            # ``intent`` on the response is a frontend hint —
            # nothing in the widget UI today branches on it for
            # agentic, but pinning "agentic" keeps the wire shape
            # honest for any future "render differently per flow"
            # treatment.
            intent="agentic",
            intent_confidence=1.0,
            message=safe_out,
            citations=result.citations or [],
            suggested_actions=result.suggested_actions or [],
            provider=provider.name,
            model_version=getattr(provider, "model", None),
        )


def _agentic_error_result(err: str):
    """Last-ditch result used when AgenticOrchestrator.handle itself
    raises (it shouldn't — but defence in depth)."""
    from app.services.assistant.agentic.orchestrator import AgenticResult
    return AgenticResult(
        message=("Sorry, I hit an error answering that. Please try "
                  "again or ask for human follow-up."),
        error=err,
    )


# --------------------------------------------------------------- shadow
# We attach this as a method on AssistantOrchestrator below by binding
# at module load — easier than re-opening the class.

def _run_shadow(
    self: "AssistantOrchestrator",
    request: AssistantRequest,
    user: User | None,
    safe_msg: str,
    decision: FlowDecision,
) -> None:
    """Run the shadow flow synchronously, log its result for offline
    comparison. NEVER raises — shadow failures must not affect the
    user-facing response.

    Today the resolver only ever sets ``decision.shadow=AGENTIC``
    (with ``primary=LEGACY``) in shadow-mode. We branch on the value
    anyway so a future "shadow=LEGACY while primary=AGENTIC" mode
    drops in cleanly.

    Logging contract:

      * One audit_log row with action='assistant.shadow.{flow}'
        capturing the shadow result for offline comparison.
      * One drift-detector pass against the shadow response, with
        flow="shadow_agentic" so dashboards segregate shadow rows
        from primary rows.
      * NO AssistantLog row — the user got the primary's turn_id;
        adding a shadow row would confuse the "flag this turn"
        feedback loop.
      * NO Redis quota tick — the user sent one message, they pay
        for one quota slot. (Endpoint already counted before
        handle().)

    Cost: every shadow-sampled request runs an additional agentic
    pipeline → ~2× LLM calls + ~2× latency for that turn. Gated by
    ``assistant.agentic.shadow_sampling_rate`` (seed default 0.0 —
    shadow disabled until an admin opts in).
    """
    started = time.monotonic()
    if decision.shadow is None:
        return     # defensive — handle() guards this too

    user_id = user.id if user else None

    if decision.shadow is Flow.AGENTIC:
        try:
            provider = LLMRegistry.get_active()
            agentic = AgenticOrchestrator(self.db, provider)
            shadow_result = agentic.handle(
                request, user, request.anon_id)
        except Exception as e:
            log.exception("assistant.shadow_failed", error=str(e))
            try:
                audit_log(self.db, user_id, "assistant.shadow.error", {
                    "primary_flow": decision.primary.value,
                    "shadow_flow":  decision.shadow.value,
                    "error": str(e),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                })
            except Exception:
                pass
            return

        shadow_message = self.guardrails.check_output(shadow_result.message)

        try:
            tools_summary = ",".join(
                t.get("name", "?") for t in (shadow_result.tools_called or [])
            ) or "(no tools)"
            audit_log(self.db, user_id, "assistant.shadow.agentic", {
                "primary_flow": decision.primary.value,
                "shadow_flow":  decision.shadow.value,
                "tools_called": shadow_result.tools_called,
                "shadow_response_preview": shadow_message[:500],
                "shadow_citations_count": len(shadow_result.citations or []),
                "shadow_error": shadow_result.error,
                "shadow_metadata": shadow_result.metadata,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            })
        except Exception:
            log.exception("assistant.shadow_audit_failed")

        # Drift detection on the shadow response. Distinct flow value
        # ("shadow_agentic") so dashboards can show "shadow agentic
        # drift" alongside "primary legacy drift" without conflating
        # them with primary-agentic traffic.
        try:
            detect_and_log(self.db, DriftContext(
                user_id=user_id,
                flow=f"shadow_{decision.shadow.value}",
                handler=tools_summary,
                intent=None,
                question=safe_msg,
                response=shadow_message,
                retrieval_count=len(shadow_result.citations or []),
            ))
        except Exception:
            log.exception("assistant.shadow_drift_failed")
        return

    # Shadow flow value the resolver doesn't currently emit — log
    # and bail out. Keeps the function future-proof against a
    # resolver change.
    log.warning("assistant.shadow_unsupported_flow",
                  shadow_flow=decision.shadow.value)


# Bind the module-level function as a method on AssistantOrchestrator
# without re-opening the class block. Same effect, slightly easier to
# read than nested-function-in-class.
AssistantOrchestrator._run_shadow = _run_shadow  # type: ignore[attr-defined]
