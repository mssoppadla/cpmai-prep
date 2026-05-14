"""Tests for the four pure-rule agentic tools — no LLM, no embedding.

Each tool is a thin wrapper around either:
  * a SQLAlchemy query (account_state, user_insights, human_escalation)
  * a settings_store lookup (pmi_reference)

Tests pin:
  * Anonymous user → ToolStatus.REFUSED_NEED_AUTH (where applicable)
  * Happy path → ToolStatus.OK + the expected content/citations
  * Empty / "not configured" → ToolStatus.EMPTY
  * No tool raises (DB errors get caught + downgraded to status=ERROR)
  * has_llm_call = False (cost accounting)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.exam_session import ExamSession
from app.models.lead import Lead, LeadSource
from app.models.subscription import Subscription

from app.services.assistant.agentic.tools.account_state import AccountStateTool
from app.services.assistant.agentic.tools.human_escalation import (
    HumanEscalationTool,
)
from app.services.assistant.agentic.tools.pmi_reference import PmiReferenceTool
from app.services.assistant.agentic.tools.user_insights import UserInsightsTool
from app.services.assistant.agentic.types import ToolContext, ToolStatus


def _ctx(*, db=None, user=None, anon_id=None):
    return ToolContext(db=db, user=user, anon_id=anon_id)


# ============================================================ shared

@pytest.mark.parametrize("tool_cls", [
    AccountStateTool, UserInsightsTool,
    PmiReferenceTool, HumanEscalationTool,
])
def test_no_llm_call_flag_is_false(tool_cls):
    """These four are the cheap ones — no embedding, no completion.
    Cost accounting depends on this."""
    assert tool_cls().has_llm_call is False


# ============================================================ account_state

class TestAccountStateTool:

    def test_requires_user(self):
        assert AccountStateTool().requires_user is True

    def test_refuses_anonymous(self):
        r = AccountStateTool().execute(_ctx(user=None), {})
        assert r.status is ToolStatus.REFUSED_NEED_AUTH
        assert r.error == "anonymous_user"

    def test_no_subscription_means_free_tier(self, db, user):
        r = AccountStateTool().execute(_ctx(db=db, user=user), {})
        assert r.status is ToolStatus.OK
        assert "free tier" in r.content.lower()
        assert r.metadata == {"has_subscription": False}

    def test_active_subscription_renders_active(self, db, user):
        future = datetime.now(timezone.utc) + timedelta(days=30)
        db.add(Subscription(
            user_id=user.id, plan="pro", status="active",
            expires_at=future,
        ))
        db.commit()
        r = AccountStateTool().execute(_ctx(db=db, user=user), {})
        assert r.status is ToolStatus.OK
        assert "ACTIVE" in r.content
        assert r.metadata["is_active"] is True
        assert r.metadata["plan"] == "pro"

    def test_expired_subscription_renders_inactive(self, db, user):
        """Same status='active' row but expires_at in the past →
        paywall sees this as INACTIVE. Aligns with the paywall's
        own logic — must stay in sync or admins see contradictory
        states."""
        past = datetime.now(timezone.utc) - timedelta(days=1)
        db.add(Subscription(
            user_id=user.id, plan="pro", status="active",
            expires_at=past,
        ))
        db.commit()
        r = AccountStateTool().execute(_ctx(db=db, user=user), {})
        assert r.status is ToolStatus.OK
        assert "INACTIVE" in r.content
        assert r.metadata["is_active"] is False


# ============================================================ user_insights

class TestUserInsightsTool:

    def test_requires_user(self):
        assert UserInsightsTool().requires_user is True

    def test_refuses_anonymous(self):
        r = UserInsightsTool().execute(_ctx(user=None), {})
        assert r.status is ToolStatus.REFUSED_NEED_AUTH

    def test_no_attempts_returns_helpful_message(self, db, user):
        r = UserInsightsTool().execute(_ctx(db=db, user=user), {})
        assert r.status is ToolStatus.OK
        assert "no submitted exam attempts" in r.content.lower()
        # Action chip nudges them to take a mock exam.
        assert r.suggested_actions
        assert r.metadata["attempts_count"] == 0

    def test_with_attempts_renders_summary(self, db, user, sample_exam_set):
        now = datetime.now(timezone.utc)
        db.add(ExamSession(
            user_id=user.id, exam_set_id=sample_exam_set.id,
            started_at=now - timedelta(hours=1),
            submitted_at=now - timedelta(minutes=45),
            expires_at=now,
            status="submitted", score=72, passed=True,
            time_taken_seconds=15 * 60,
        ))
        db.commit()
        r = UserInsightsTool().execute(_ctx(db=db, user=user), {})
        assert r.status is ToolStatus.OK
        assert "72%" in r.content
        assert "passed" in r.content
        assert r.metadata["attempts_count"] == 1


# ============================================================ pmi_reference

class TestPmiReferenceTool:

    def test_does_not_require_user(self):
        """PMI is the same URL whether you're signed in or not."""
        assert PmiReferenceTool().requires_user is False

    def test_unknown_intent_is_error(self):
        r = PmiReferenceTool().execute(_ctx(), {"intent": "renewal"})
        assert r.status is ToolStatus.ERROR
        assert "unknown intent" in (r.error or "")

    def test_missing_url_returns_empty_status(self):
        """Admin hasn't configured ``pmi.eco_url`` yet → don't
        invent a URL. Status EMPTY so synthesis tells the user to
        search pmi.org instead of hallucinating."""
        with patch("app.services.assistant.agentic.tools.pmi_reference"
                    ".settings_store.get_str", return_value=""):
            r = PmiReferenceTool().execute(_ctx(), {"intent": "eco"})
        assert r.status is ToolStatus.EMPTY
        assert "search" in r.content.lower()

    def test_eco_intent_returns_eco_url(self):
        url = "https://www.pmi.org/cpmai/eco"
        with patch("app.services.assistant.agentic.tools.pmi_reference"
                    ".settings_store.get_str",
                    side_effect=lambda k, d="": url if k == "pmi.eco_url" else ""):
            r = PmiReferenceTool().execute(_ctx(), {"intent": "eco"})
        assert r.status is ToolStatus.OK
        assert url in r.content
        assert r.citations[0]["url"] == url
        assert r.suggested_actions[0]["url"] == url

    def test_course_intent_returns_course_url(self):
        url = "https://www.pmi.org/cpmai"
        with patch("app.services.assistant.agentic.tools.pmi_reference"
                    ".settings_store.get_str",
                    side_effect=lambda k, d="": url if k == "pmi.course_bundle_url" else ""):
            r = PmiReferenceTool().execute(_ctx(), {"intent": "course"})
        assert r.status is ToolStatus.OK
        assert url in r.content


# ============================================================ human_escalation

class TestHumanEscalationTool:

    def test_requires_user(self):
        assert HumanEscalationTool().requires_user is True

    def test_refuses_anonymous(self):
        r = HumanEscalationTool().execute(
            _ctx(user=None), {"reason": "user asked"})
        assert r.status is ToolStatus.REFUSED_NEED_AUTH

    def test_empty_reason_is_error(self, db, user):
        r = HumanEscalationTool().execute(
            _ctx(db=db, user=user), {"reason": "   "})
        assert r.status is ToolStatus.ERROR
        assert "reason" in (r.error or "")

    def test_happy_path_inserts_lead_row(self, db, user):
        before = db.query(Lead).count()
        r = HumanEscalationTool().execute(
            _ctx(db=db, user=user),
            {"reason": "user explicitly asked for callback",
             "phone": "+1-555-0000",
             "note":  "best after 5pm PT"},
        )
        assert r.status is ToolStatus.OK
        assert db.query(Lead).count() == before + 1
        row = db.query(Lead).order_by(Lead.id.desc()).first()
        assert row.email == user.email
        assert row.phone == "+1-555-0000"
        assert row.source == LeadSource.CHAT_CALLBACK
        # reason + note threaded through interests JSON
        assert any("user explicitly asked" in s for s in row.interests)
        assert any("best after 5pm" in s for s in row.interests)
        # tool returns the new row id in metadata for audit log
        assert r.metadata["lead_id"] == row.id

    def test_long_reason_is_truncated(self, db, user):
        r = HumanEscalationTool().execute(
            _ctx(db=db, user=user),
            {"reason": "x" * 1000},
        )
        assert r.status is ToolStatus.OK
        row = db.query(Lead).order_by(Lead.id.desc()).first()
        # 200-char cap on the reason segment.
        assert len(row.interests[0]) < 300

    def test_no_phone_no_note_still_works(self, db, user):
        r = HumanEscalationTool().execute(
            _ctx(db=db, user=user), {"reason": "stuck"})
        assert r.status is ToolStatus.OK
        row = db.query(Lead).order_by(Lead.id.desc()).first()
        assert row.phone is None
        # interests has the reason, no note row
        assert len(row.interests) == 1
        assert r.metadata["phone_provided"] is False
        assert r.metadata["note_provided"] is False
