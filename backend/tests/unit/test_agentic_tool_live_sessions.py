"""live_sessions tool — upcoming class schedule from the live DB.

Pins:
  * anonymous users allowed (requires_user=False) — schedule is public
  * upcoming scheduled/live sessions listed in date order with the
    date, duration, and linked course title
  * drafts / cancelled / long-past sessions excluded
  * join/start URLs NEVER appear in the output
  * registration CTA rides along when the landing banner link is set
  * DB failure degrades to status=ERROR, never raises
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.lms import Course
from app.models.zoom import ZoomSession
from app.services.assistant.agentic.tools.live_sessions import LiveSessionsTool
from app.services.assistant.agentic.types import ToolContext, ToolStatus


def _ctx(db):
    return ToolContext(db=db, user=None, anon_id="anon-1")


def _session(db, title, *, offset_hours, status="scheduled", **kw):
    s = ZoomSession(
        title=title, status=status,
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=offset_hours),
        **kw)
    db.add(s); db.commit(); db.refresh(s)
    return s


def test_is_public_and_cheap():
    t = LiveSessionsTool()
    assert t.requires_user is False
    assert t.has_llm_call is False


def test_lists_upcoming_in_order_without_join_urls(db):
    c = Course(slug="c1", title="Fundamentals", is_published=True)
    db.add(c); db.commit(); db.refresh(c)
    _session(db, "Later session", offset_hours=72, course_id=c.id)
    _session(db, "Sooner session", offset_hours=24,
             zoom_join_url="https://zoom.us/j/secret123")
    _session(db, "Draft one", offset_hours=48, status="draft")
    _session(db, "Cancelled one", offset_hours=48, status="cancelled")
    _session(db, "Long past", offset_hours=-100, status="scheduled")

    r = LiveSessionsTool().execute(_ctx(db), {})
    assert r.status is ToolStatus.OK
    assert r.content.index("Sooner session") < r.content.index("Later session")
    assert "Draft one" not in r.content
    assert "Cancelled one" not in r.content
    assert "Long past" not in r.content
    assert "secret123" not in r.content
    assert "part of course: Fundamentals" in r.content
    assert r.metadata["session_count"] == 2


def test_recently_started_session_still_listed(db):
    """A session that started an hour ago may still be running —
    the 3h grace window keeps it visible."""
    _session(db, "Running now", offset_hours=-1, status="live")
    r = LiveSessionsTool().execute(_ctx(db), {})
    assert "Running now" in r.content


def test_empty_schedule_is_ok_not_error(db):
    r = LiveSessionsTool().execute(_ctx(db), {})
    assert r.status is ToolStatus.OK
    assert "No upcoming live class sessions" in r.content
    assert r.metadata["session_count"] == 0


def test_registration_action_from_banner_setting(db):
    _session(db, "Any", offset_hours=24)
    with patch("app.services.assistant.agentic.tools.live_sessions."
               "settings_store") as ss:
        ss.get_str.return_value = "https://zoom.us/meeting/register/x"
        r = LiveSessionsTool().execute(_ctx(db), {})
    assert r.suggested_actions == [
        {"label": "Register for live classes",
         "url": "https://zoom.us/meeting/register/x"}]


def test_db_failure_degrades_to_error(db):
    class Boom:
        def query(self, *a, **k):
            raise RuntimeError("db down")
    r = LiveSessionsTool().execute(ToolContext(db=Boom(), user=None,
                                                anon_id=None), {})
    assert r.status is ToolStatus.ERROR
    assert "db lookup failed" in (r.error or "")
