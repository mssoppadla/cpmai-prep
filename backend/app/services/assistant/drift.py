"""Post-response drift detection for the assistant.

Runs after every chat turn, against the LLM's response + the retrieval
state that fed it. Each detector rule is a small function that returns
either ``None`` (no drift seen) or a ``DriftEvent`` describing what
went wrong. The orchestrator runs all rules and writes any positive
events to ``audit_log`` with the action prefix ``assistant.drift.*``.
The /admin/assistant-drift dashboard reads them back, grouping by:

  * ``flow``    — "legacy" (regex classifier + single handler) or
                  "agentic" (LLM tool routing + synthesis, future)
  * ``reason``  — which rule fired (refused_with_context, etc.)
  * ``handler`` — which handler ran (legacy) or which tools (agentic)

Why a rule registry rather than inline checks in the orchestrator:

  1. Rules are independently testable.
  2. New rules are one ``DriftRule`` object — natural extension point
     when the agentic toggle ships and adds tool-specific failure
     modes (wrong_tool_selected, multi_tool_only_cited_one,
     tool_call_syntax_error).
  3. Disabling a noisy rule in prod is one constant edit, not a
     surgical patch.

Schema discriminator is the ``flow`` field — every event from today's
code path carries ``flow="legacy"``. The agentic path will write
``flow="agentic"`` against the same audit_log table, letting the
dashboard render side-by-side comparisons without any further wiring.
"""
import re
from dataclasses import dataclass
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.settings_store import settings_store


@dataclass
class DriftContext:
    """Inputs to drift rules. Captures everything a rule might need to
    decide whether the LLM's response was off, and everything the
    audit_log row should preserve for later analysis.

    ``retrieval_count`` is just the count (typically ``len(citations)``)
    rather than the full chunk objects — none of the rules need chunk
    contents, only the answer to "did RAG return anything." Keeping
    this lean means the orchestrator can pass a count without
    plumbing chunk lists out of handlers."""
    user_id: Optional[int]
    flow: str                       # "legacy" or "agentic"
    handler: str                    # legacy: handler name; agentic: comma-joined tools
    intent: Optional[str]           # legacy: classifier intent (FAQ/CONTENT/...)
    question: str
    response: str
    retrieval_count: int = 0


@dataclass
class DriftEvent:
    """One detected drift signature. Becomes one audit_log row.

    `reason` is also the audit-log action SUFFIX — the row's full
    action is ``assistant.drift.{reason}``. Keep these snake_case
    + identifier-shaped so dashboard filters can use them directly.
    """
    reason: str
    detail: str
    severity: str = "warn"          # "warn" | "error" — rolled up in dashboard


# ============================================================ rules


# Refusal phrases the LLM tends to emit when it decides a topic is out
# of scope. Lowercased substrings; checked against the lowercased
# response. Tuned to be precise — false positives here look bad on
# the dashboard. If the operator sees noise from a genuine refusal
# being flagged, edit this list; it's intentionally narrow.
_REFUSAL_PHRASES = (
    "outside the scope",
    "outside of the scope",
    "outside my scope",
    "i'm unable to provide",
    "i am unable to provide",
    "i cannot help with",
    "i can't help with",
    "i don't have information",
    "i do not have information",
    "i don't have access",
    "i do not have access",
)

# Citation reference pattern that handlers ask the LLM to use. Matches
# "[Source 3]" / "[source 12]" — case-insensitive, allows whitespace.
_CITATION_PATTERN = re.compile(r"\[\s*source\s+(\d+)\s*\]", re.IGNORECASE)


def _refused_with_context(ctx: DriftContext) -> Optional[DriftEvent]:
    """The most operator-actionable signal. The LLM said "outside scope"
    but RAG actually retrieved chunks that should have been useful.
    Indicates either:
      * a SYSTEM prompt that's too narrow → operator edits the
        handler's system prompt to broaden scope
      * a topic the operator wants to allow → adds to
        assistant.allowed_exceptions
      * the wrong handler being routed → fix the classifier or wait
        for the agentic toggle
    """
    if not ctx.retrieval_count:
        return None
    lowered = ctx.response.lower()
    for phrase in _REFUSAL_PHRASES:
        if phrase in lowered:
            return DriftEvent(
                reason="refused_with_context",
                detail=(f"LLM refused with phrase '{phrase}' but "
                        f"{ctx.retrieval_count} chunks were retrieved"),
                severity="warn",
            )
    return None


def _empty_response(ctx: DriftContext) -> Optional[DriftEvent]:
    """LLM returned essentially nothing. Usually a provider hiccup,
    occasionally a too-strict guardrail clipping output. Cheap to
    detect; high signal for "the user got a broken experience."""
    if len(ctx.response.strip()) < 20:
        return DriftEvent(
            reason="empty_response",
            detail=f"Response was {len(ctx.response.strip())} chars",
            severity="error",
        )
    return None


def _missing_citation(ctx: DriftContext) -> Optional[DriftEvent]:
    """We retrieved chunks AND the system prompt asked the LLM to cite,
    but the response has no [Source N] markers. The user will get an
    answer with no provenance — bad UX, bad trust signal."""
    if not ctx.retrieval_count:
        return None
    if _CITATION_PATTERN.search(ctx.response):
        return None
    return DriftEvent(
        reason="missing_citation",
        detail=(f"{ctx.retrieval_count} chunks retrieved but "
                "no [Source N] reference in response"),
        severity="warn",
    )


def _invented_citation(ctx: DriftContext) -> Optional[DriftEvent]:
    """LLM cited [Source N] for an N that's beyond the chunks we
    actually provided. Hallucinated citation → user clicks the chip
    expecting evidence and finds nothing. Pin this hard."""
    n_chunks = ctx.retrieval_count
    cited = [int(m.group(1)) for m in _CITATION_PATTERN.finditer(ctx.response)]
    invented = [n for n in cited if n < 1 or n > n_chunks]
    if not invented:
        return None
    return DriftEvent(
        reason="invented_citation",
        detail=(f"Response cited Source(s) {invented}; only "
                f"{n_chunks} were provided"),
        severity="error",
    )


# Rule registry. ORDER MATTERS only insofar as the dashboard groups
# events by reason — every rule still runs against every context.
# Adding a new rule = append a function to this list.
DRIFT_RULES: list[Callable[[DriftContext], Optional[DriftEvent]]] = [
    _refused_with_context,
    _empty_response,
    _missing_citation,
    _invented_citation,
]


# ============================================================ orchestration

def detect_and_log(db: Session, ctx: DriftContext) -> list[DriftEvent]:
    """Run every rule against the context, write any drift events to
    audit_log, return the list (for tests; orchestrator ignores it).

    Audit log shape:
      action     = "assistant.drift.{reason}"
      user_id    = the chat user (None for anon)
      metadata_json = full DriftContext serialised, plus the event's
                      detail string + severity.

    Operator dashboards filter on action prefix and group by the
    metadata fields. The audit_log table is already indexed on
    (created_at, action) for the existing /admin/audit-logs view, so
    drift queries piggyback on the same index without new migrations.
    """
    if not _enabled():
        return []
    events: list[DriftEvent] = []
    for rule in DRIFT_RULES:
        try:
            ev = rule(ctx)
        except Exception:
            # Rule crashed — don't take down the chat over a misbehaving
            # detector. Eat it; drift detection is best-effort.
            continue
        if ev:
            events.append(ev)

    for ev in events:
        # Truncate the question + response previews so a few thousand
        # drift events don't blow up the audit_log row size.
        meta = {
            "flow": ctx.flow,
            "handler": ctx.handler,
            "intent": ctx.intent,
            "drift_reason": ev.reason,
            "severity": ev.severity,
            "detail": ev.detail,
            "retrieval_chunks_count": ctx.retrieval_count,
            "question_excerpt": ctx.question[:240],
            "response_excerpt": ctx.response[:240],
        }
        try:
            audit_log(db, ctx.user_id, f"assistant.drift.{ev.reason}", meta)
        except Exception:
            # Don't take down the chat if the audit write fails.
            pass

    return events


def _enabled() -> bool:
    """Off by default — flip via /admin/settings →
    assistant.drift_detection_enabled. Operator-controlled so they can
    turn it off if a rule gets noisy without a redeploy."""
    return bool(settings_store.get("assistant.drift_detection_enabled", False))
