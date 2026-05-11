"""Day-1 RAG slice: PMI handler + intent classifier + reindex hooks.

What's NOT tested here:
  - Live retrieval against pgvector — SQLite test env doesn't have the
    extension. Retrieval is integration-tested in prod via the smoke
    after deploy.
  - OpenAI embedding calls — we never make them in tests; the registry
    raises if no provider is configured, and handlers gracefully fall
    back to a no-RAG answer.

What IS tested:
  - PmiReferenceHandler returns deterministic responses keyed off
    settings_store (no LLM, no embeddings) — admins can configure URLs
    and the chat surfaces them.
  - IntentClassifier routes PMI-flavoured questions to PMI_REFERENCE
    BEFORE they get caught by the broader FAQ intent.
  - CRUD hooks call reindex_quietly with the right source_type +
    source_id; reindex_quietly itself swallows exceptions (so RAG
    failures don't kill the admin's save).
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.assistant.intent_classifier import IntentClassifier, Intent
from app.services.assistant.handlers.pmi_handler import PmiReferenceHandler
from app.services.assistant.rag.ingest import reindex_quietly
from tests.conftest import auth_header


# ==================================== intent classifier (specificity)
@pytest.mark.parametrize("msg", [
    "where do i register for the cpmai exam?",
    "tell me about the course bundle link",
    "what's the exam content outline",
    "show me the eco",
    "what's on the exam?",
    "tell me about pmi.org",
])
def test_pmi_keywords_route_to_pmi_intent(msg):
    """PMI_REFERENCE must be checked BEFORE FAQ — otherwise "where do
    I register for the exam" gets caught by 'schedule' / 'eligibility'
    in FAQ and the user loses the direct link."""
    intent, _ = IntentClassifier().classify(msg)
    assert intent == Intent.PMI_REFERENCE, f"{msg!r} → {intent.value}"


def test_pricing_words_still_route_to_account():
    """Sanity — the PMI re-ordering doesn't break the existing intents."""
    for msg in ["how much is the plan", "what's the pricing",
                 "I want a refund", "discount code"]:
        intent, _ = IntentClassifier().classify(msg)
        assert intent == Intent.ACCOUNT, f"{msg!r} → {intent.value}"


def test_faq_phrasings_still_route_to_faq():
    for msg in ["exam pattern", "what's the passing percentage",
                 "is there an eligibility requirement"]:
        intent, _ = IntentClassifier().classify(msg)
        # 'passing' is FAQ; 'eligibility' is FAQ. None overlap with
        # the PMI keyword list.
        assert intent == Intent.FAQ, f"{msg!r} → {intent.value}"


# ==================================== PMI handler — deterministic, no LLM
@pytest.fixture
def mock_settings(monkeypatch):
    """Override settings_store to return canned PMI URLs without
    needing a populated DB row."""
    canned = {
        "pmi.course_bundle_url": "https://www.pmi.org/cpmai/course",
        "pmi.eco_url": "https://www.pmi.org/cpmai/eco",
    }
    from app.core import settings_store as ss
    monkeypatch.setattr(ss.SettingsStore, "get_str",
        lambda self, k, default="": canned.get(k, default))


def _fake_request(message: str):
    """Build a minimal request object — handler only reads .message."""
    r = MagicMock()
    r.message = message
    return r


def test_pmi_handler_returns_course_url_on_register_intent(db, mock_settings):
    h = PmiReferenceHandler(db, provider=MagicMock())
    resp = h.respond(_fake_request("where do I register for the exam"), user=None)
    assert "pmi.org/cpmai/course" in resp["message"]
    assert resp["citations"][0]["url"] == "https://www.pmi.org/cpmai/course"
    assert resp["suggested_actions"][0]["url"] == "https://www.pmi.org/cpmai/course"


def test_pmi_handler_returns_eco_url_on_outline_intent(db, mock_settings):
    h = PmiReferenceHandler(db, provider=MagicMock())
    resp = h.respond(_fake_request("what's on the exam content outline"), user=None)
    assert "pmi.org/cpmai/eco" in resp["message"]


def test_pmi_handler_prefers_eco_when_both_keywords_match(db, mock_settings):
    """When the message mentions both 'register' AND 'content outline',
    ECO (more specific) wins."""
    h = PmiReferenceHandler(db, provider=MagicMock())
    resp = h.respond(
        _fake_request("how do I register and what's the exam content outline"),
        user=None)
    assert "pmi.org/cpmai/eco" in resp["message"]


def test_pmi_handler_falls_back_when_url_not_configured(db, monkeypatch):
    """If admin hasn't set the URL, return a generic pointer rather
    than a broken link."""
    from app.core import settings_store as ss
    monkeypatch.setattr(ss.SettingsStore, "get_str",
        lambda self, k, default="": default)
    h = PmiReferenceHandler(db, provider=MagicMock())
    resp = h.respond(_fake_request("where do I register"), user=None)
    assert "pmi.org" in resp["message"]
    assert resp["citations"] == []


# ==================================== reindex hooks (admin CRUD wiring)
def _capture_reindex_calls(monkeypatch) -> list:
    """Returns a list that captures every reindex_quietly invocation
    so tests can assert which (source_type, source_id) was scheduled.

    Patches the symbol at the IMPORT SITE inside each admin endpoint
    module (not the definition site) — reindex_quietly was bound into
    those namespaces at import time."""
    calls: list[tuple[str, int | str]] = []
    def fake(_db, source_type, source_id):
        calls.append((source_type, source_id))
    monkeypatch.setattr("app.api.v1.endpoints.admin.faqs.reindex_quietly", fake)
    monkeypatch.setattr("app.api.v1.endpoints.admin.plans.reindex_quietly", fake)
    monkeypatch.setattr("app.api.v1.endpoints.admin.questions.reindex_quietly", fake)
    return calls


def test_faq_create_triggers_reindex(client, admin, monkeypatch):
    calls = _capture_reindex_calls(monkeypatch)
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/faqs", headers=h, json={
        "question": "What is CPMAI?",
        "answer": "Certified Professional in Machine Learning + AI.",
        "display_order": 100, "is_active": True,
    })
    assert r.status_code == 201
    faq_id = r.json()["id"]
    assert ("faq", faq_id) in calls


def test_faq_update_triggers_reindex(client, admin, db, monkeypatch):
    """Pre-create directly so the create hook doesn't pollute the call list."""
    from app.models.faq import FaqItem
    f = FaqItem(question="Pre-existing", answer="...",
                 display_order=10, is_active=True)
    db.add(f); db.commit(); db.refresh(f)

    calls = _capture_reindex_calls(monkeypatch)
    h = auth_header(client, admin.email)
    r = client.patch(f"/api/v1/admin/faqs/{f.id}", headers=h, json={
        "question": "Pre-existing", "answer": "Updated answer.",
        "display_order": 10, "is_active": True,
    })
    assert r.status_code == 200
    assert ("faq", f.id) in calls


def test_question_create_triggers_reindex(client, admin, db, monkeypatch):
    calls = _capture_reindex_calls(monkeypatch)
    from app.models.topic import Topic
    du = db.query(Topic).filter_by(code="DU").first()
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/questions", headers=h, json={
        "stem": "Sample question to test reindex hook?",
        "topic_id": du.id, "difficulty": "easy",
        "explanation": "Why this answer is right.",
        "options": [
            {"option_letter": "A", "text": "yes", "is_correct": True},
            {"option_letter": "B", "text": "no",  "is_correct": False},
        ],
    })
    assert r.status_code == 201
    qid = r.json()["id"]
    assert ("question_explanation", qid) in calls


def test_plan_create_triggers_reindex(client, admin, monkeypatch):
    calls = _capture_reindex_calls(monkeypatch)
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/plans", headers=h, json={
        "name": "Test Bundle for reindex", "slug": "test-reindex-bundle",
        "bundle_type": "exam_bundle", "base_price_paise": 10000,
    })
    assert r.status_code == 201
    pid = r.json()["id"]
    assert ("plan", pid) in calls


# ==================================== reindex_quietly fault-tolerance
def test_reindex_quietly_swallows_exceptions(db, monkeypatch):
    """Critical invariant: a RAG re-embed failure (OpenAI down,
    network blip, pgvector missing) MUST NOT bubble up and crash the
    admin's save. The user's primary action — saving their FAQ /
    plan / question — completes successfully; the reindex is
    best-effort and logged for later retry."""
    def explode(_db, _st, _sid):
        raise RuntimeError("simulated OpenAI 500")
    monkeypatch.setattr(
        "app.services.assistant.rag.ingest.reindex_source_id", explode)
    # Must NOT raise:
    reindex_quietly(db, "faq", 1)


# ==================================== admin reindex endpoint contract
def test_reindex_endpoint_requires_admin(client, user):
    """Regular users can't trigger a corpus rebuild."""
    h = auth_header(client, user.email)
    r = client.post("/api/v1/admin/rag/reindex", headers=h)
    assert r.status_code in (401, 403)


def test_reindex_endpoint_reports_400_when_embeddings_unconfigured(
        client, admin, monkeypatch):
    """No embeddings.provider_id set → friendly 400, not a 500.

    Patch at the endpoint's import site — `reindex_all` was bound into
    the admin.rag module's namespace at module load, so patching the
    original definition in `ingest` wouldn't reach it."""
    def explode(*a, **kw):
        raise RuntimeError("Embeddings not configured.")
    monkeypatch.setattr(
        "app.api.v1.endpoints.admin.rag.reindex_all", explode)

    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/rag/reindex", headers=h)
    assert r.status_code == 400
    assert "Embeddings not configured" in r.json()["error"]["message"]


def test_rag_status_groups_by_source_type(client, admin):
    """Even with zero indexed chunks, status returns one entry per
    known source_type — admin UI never breaks on a fresh deploy."""
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/rag/status", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "sources" in body
    for st in ("faq", "plan", "question_explanation"):
        assert st in body["sources"]
        assert body["sources"][st]["chunks"] == 0
