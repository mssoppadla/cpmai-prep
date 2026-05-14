"""End-to-end value-prop tests for the legacy → agentic toggle.

These tests pin the BEHAVIOURAL DIFFERENCE between the two flows using
the existing drift detector as the oracle:

  * **Legacy** answers a non-keyword-matching question by falling
    through to the admin-configured default handler. If the handler's
    LLM hits an off-topic refusal pattern despite retrieved chunks
    being available, the drift detector tags it as
    ``refused_with_context``. This is the canonical "wrong handler
    + narrow system prompt" failure mode operators see today.

  * **Agentic** (when implemented in a follow-up PR) should route the
    same question via the router → relevant tool(s) → synthesis, and
    NOT trigger a drift event. The same question that drifted in
    legacy lands a clean answer in agentic.

Why this is the right contract test:

  * Doesn't depend on real LLM behaviour — uses the StubProvider with
    an admin-configured refusal phrase, so the LLM side is
    deterministic across CI runs.
  * Doesn't depend on pgvector being seeded — patches
    ``retrieve_context`` so handlers see a non-empty chunk list
    without needing a real embeddings provider.
  * Uses the drift detector that's already shipping — the test is
    measuring exactly what the operator dashboard will measure.
  * Pins both ends of the comparison: legacy SHOULD drift on this
    case (proof the test setup is meaningful); agentic SHOULD NOT
    drift (proof the new flow earns its complexity).

When the agentic implementation lands, the ``xfail`` marker on the
agentic test is removed and it becomes the gating contract.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.audit_log import AuditLog
from app.services.assistant.rag.retrieve import RetrievedChunk
from tests.conftest import auth_header


# ===================================================== shared setup helpers

# A question that, under the LEGACY keyword classifier, matches NO
# keyword and falls through to the admin-configured default intent
# ("content" by default). The default handler's LLM (stubbed below)
# returns a refusal phrase, which the drift detector tags because
# retrieval returned chunks.
#
# Why this question: the EU AI Act + exam framing is realistic
# (operators have asked about this kind of cross-topic question in
# prod) and it deliberately mixes a non-classifier topic (EU AI Act)
# with a chat-bot-trigger keyword (exam) that ALMOST matches FAQ but
# doesn't quite — "for the exam" isn't in any FAQ keyword. Captures
# the long-tail intent that legacy fumbles.
_PROBLEMATIC_QUESTION = "Should I memorise the EU AI Act for the exam?"

# Refusal phrase keyed into _REFUSAL_PHRASES in drift.py. Using one
# the detector explicitly lists means a future tweak that removes
# our test phrase from the rule set will surface in
# tests/unit/test_assistant_drift.py first, not silently break here.
_REFUSAL_TEXT = (
    "I cannot help with that — that's outside the scope of CPMAI "
    "topics. Try asking about the certification process instead."
)


def _patch_setting(client, admin, key: str, value):
    """Round-trip through the real admin/settings PATCH so the test
    exercises validator + cache-invalidation paths, not just direct
    DB writes."""
    h = auth_header(client, admin.email)
    r = client.patch(f"/api/v1/admin/settings/{key}",
                      headers=h, json={"value": value})
    assert r.status_code == 200, (
        f"failed to PATCH {key}={value!r}: {r.status_code} {r.text}")


def _fake_chunk() -> RetrievedChunk:
    """One synthetic chunk so the drift rule's
    ``retrieval_count > 0`` precondition is satisfied. The content
    doesn't need to be relevant — drift only checks count, not
    semantics."""
    return RetrievedChunk(
        chunk_id=1,
        source_type="upload",
        source_id="test-doc",
        content=(
            "The EU AI Act is a comprehensive regulation. Article 6 "
            "defines high-risk AI systems. This document is part of "
            "the admin-uploaded reference corpus."
        ),
        similarity=0.5,
        metadata={"filename": "ai_act.md", "chunk_index": 0},
    )


def _patch_rag_for_all_handlers():
    """Patch ``retrieve_context`` in every handler module that imports it.

    Each handler re-imports the function into its own module namespace
    (``from … import retrieve_context``), so a single patch on
    handler_support.py wouldn't catch them — Python re-binds names at
    import time. Returns a list of patch context-managers to be
    applied as a stack.

    We pick CONTENT here because the question routes there under the
    "content" default. Patching the other handler modules anyway keeps
    the test robust if an admin (or a future test) changes the default."""
    chunk = _fake_chunk()
    targets = [
        "app.services.assistant.handlers.content_handler.retrieve_context",
        "app.services.assistant.handlers.faq_handler.retrieve_context",
        "app.services.assistant.handlers.account_handler.retrieve_context",
    ]
    return [patch(t, return_value=[chunk]) for t in targets]


def _drift_rows(db, *, flow: str | None = None,
                 reason: str = "refused_with_context") -> list[AuditLog]:
    """Read drift events from audit_log, optionally filtered by flow."""
    q = (db.query(AuditLog)
         .filter(AuditLog.action == f"assistant.drift.{reason}"))
    rows = q.all()
    if flow is not None:
        rows = [r for r in rows if (r.metadata_json or {}).get("flow") == flow]
    return rows


# ============================================================ legacy contract

def test_legacy_flow_triggers_refused_with_context_drift(client, admin, db):
    """LEGACY VALUE-PROP TEST — runs today, locks in the operator-visible
    failure mode the agentic flow should fix.

    Setup:
      * flow=legacy (seed default, but set explicitly for clarity)
      * drift detection enabled
      * classifier default = content (explicit to avoid coupling to
        the seed default)
      * stub LLM configured to return a refusal phrase verbatim
      * RAG mocked to return one chunk so the
        ``refused_with_context`` rule's retrieval_count > 0
        precondition is satisfied

    Expected:
      * Chat returns 200 (handler succeeded, even though the answer
        is a refusal — that's the point)
      * One audit_log row with action=assistant.drift.refused_with_context
        and metadata.flow="legacy"
    """
    _patch_setting(client, admin, "assistant.flow", "legacy")
    _patch_setting(client, admin, "assistant.drift_detection_enabled", True)
    _patch_setting(client, admin, "assistant.classifier.default_intent", "content")
    _patch_setting(client, admin, "assistant.no_provider_message", _REFUSAL_TEXT)

    rag_patches = _patch_rag_for_all_handlers()
    with rag_patches[0], rag_patches[1], rag_patches[2]:
        client.cookies.set("aid", "anon-legacy-drift")
        r = client.post("/api/v1/assistant/chat",
                         json={"message": _PROBLEMATIC_QUESTION})
        assert r.status_code == 200, r.text
        # Sanity: the stub LLM actually returned our refusal phrase.
        assert "cannot help" in r.json()["message"].lower()

    rows = _drift_rows(db, flow="legacy", reason="refused_with_context")
    assert len(rows) == 1, (
        f"expected exactly one refused_with_context drift event for "
        f"flow=legacy, got {len(rows)}.\n"
        f"All drift rows: {[(r.action, r.metadata_json) for r in _drift_rows(db, flow=None)]}")
    meta = rows[0].metadata_json
    assert meta["flow"] == "legacy"
    assert meta["drift_reason"] == "refused_with_context"
    assert meta["handler"] == "content"     # default routing
    assert meta["retrieval_chunks_count"] == 1


def test_legacy_no_drift_when_handler_succeeds(client, admin, db):
    """NEGATIVE CONTROL — confirms our test setup isn't producing
    false drift signals from somewhere else.

    Same setup as the test above, but the LLM returns a normal
    answer (not a refusal phrase). The drift detector should write
    NOTHING.
    """
    _patch_setting(client, admin, "assistant.flow", "legacy")
    _patch_setting(client, admin, "assistant.drift_detection_enabled", True)
    _patch_setting(client, admin, "assistant.classifier.default_intent", "content")
    # A normal answer that cites the [Source 1] chunk — satisfies
    # missing_citation rule too.
    _patch_setting(client, admin, "assistant.no_provider_message",
                    "The EU AI Act sorts AI systems by risk [Source 1]. "
                    "It's not on the CPMAI exam directly, but it informs "
                    "trustworthy-AI design discussions.")

    rag_patches = _patch_rag_for_all_handlers()
    with rag_patches[0], rag_patches[1], rag_patches[2]:
        client.cookies.set("aid", "anon-legacy-no-drift")
        r = client.post("/api/v1/assistant/chat",
                         json={"message": _PROBLEMATIC_QUESTION})
        assert r.status_code == 200

    # Zero drift events of any reason — the answer was clean.
    for reason in ("refused_with_context", "empty_response",
                    "missing_citation", "invented_citation"):
        rows = _drift_rows(db, flow="legacy", reason=reason)
        assert len(rows) == 0, (
            f"unexpected {reason} drift on a clean answer: "
            f"{rows[0].metadata_json if rows else None}")


# ============================================================ agentic contract

@pytest.mark.xfail(
    strict=True,
    reason=(
        "Agentic flow is not yet implemented — see "
        "feat/agentic-toggle-foundation. This test inverts the "
        "legacy contract: same problematic question routed through "
        "the agentic flow should produce NO drift event. When "
        "agentic ships, remove the xfail marker; the strict=True "
        "ensures we don't forget."
    ),
)
def test_agentic_flow_avoids_drift_on_same_problematic_question(
    client, admin, db,
):
    """AGENTIC VALUE-PROP TEST — locks in the contract for the
    follow-up PR.

    Same input that drifted in legacy must NOT drift in agentic:
    the router picks a relevant tool (content_search / pmi_reference),
    synthesis produces a grounded answer (not a refusal), drift
    detector finds no signature to fire.

    Until the agentic implementation lands, ``flow=agentic`` raises
    NotImplementedError → HTTP 500 → no chat response → no drift
    rows → the assertion about zero rows trivially holds. The xfail
    is on the BEHAVIOUR contract overall (which requires both
    the 200 response AND zero drift) — strict=True so the test
    starting to pass alerts us that it's time to remove xfail and
    treat the assertion as production-gating.
    """
    _patch_setting(client, admin, "assistant.flow", "agentic")
    _patch_setting(client, admin, "assistant.drift_detection_enabled", True)
    _patch_setting(client, admin, "assistant.classifier.default_intent", "content")
    # When agentic ships, the synthesis LLM should produce a real
    # answer rather than the refusal phrase. The mock here will be
    # replaced with a router/synthesis mock in the agentic PR.
    _patch_setting(client, admin, "assistant.no_provider_message",
                    "The EU AI Act isn't on the CPMAI exam directly, but [Source 1] "
                    "covers its relationship to trustworthy-AI principles.")

    rag_patches = _patch_rag_for_all_handlers()
    with rag_patches[0], rag_patches[1], rag_patches[2]:
        client.cookies.set("aid", "anon-agentic-drift")
        r = client.post("/api/v1/assistant/chat",
                         json={"message": _PROBLEMATIC_QUESTION})
        # Today this is a 500 from NotImplementedError — agentic
        # implementation will return 200.
        assert r.status_code == 200, (
            f"agentic flow returned {r.status_code}: {r.text}")

    rows = _drift_rows(db, flow="agentic", reason="refused_with_context")
    assert len(rows) == 0, (
        f"agentic flow drifted on a question it should handle correctly: "
        f"{rows[0].metadata_json if rows else None}")
