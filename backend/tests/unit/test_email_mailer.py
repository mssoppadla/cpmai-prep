"""Unit tests for the transactional-email mailer.

Covers placeholder rendering, template selection-by-source (with default
fallback), context building from the live offer settings, and the SMTP
send path (with smtplib mocked — no real network)."""
import smtplib
from datetime import datetime, timedelta, timezone

import pytest

from app.services.email import mailer
from app.models.email_template import EmailTemplate
from app.models.offer import OfferCode


# ----------------------------------------------------------- render
def test_render_substitutes_known_placeholders():
    out = mailer.render_template(
        "Hi {{name}}, code {{offer_code}}",
        {"name": "Alex", "offer_code": "WELCOME20"})
    assert out == "Hi Alex, code WELCOME20"


def test_render_leaves_unknown_placeholders_verbatim():
    out = mailer.render_template("Hi {{nope}}", {"name": "Alex"})
    assert out == "Hi {{nope}}"


def test_render_none_value_blanks():
    out = mailer.render_template("[{{offer_valid_until}}]",
                                 {"offer_valid_until": None})
    assert out == "[]"


# ----------------------------------------------------------- select_template
def test_select_prefers_source_specific(db):
    db.add(EmailTemplate(source=None, subject="default",
                         html_body="d", is_active=True))
    db.add(EmailTemplate(source="landing_hero", subject="hero",
                         html_body="h", is_active=True))
    db.commit()
    tpl = mailer.select_template(db, "landing_hero")
    assert tpl is not None and tpl.subject == "hero"


def test_select_falls_back_to_default(db):
    db.add(EmailTemplate(source=None, subject="default",
                         html_body="d", is_active=True))
    db.commit()
    tpl = mailer.select_template(db, "exit_intent")
    assert tpl is not None and tpl.subject == "default"


def test_select_ignores_inactive(db):
    db.add(EmailTemplate(source="landing_hero", subject="hero",
                         html_body="h", is_active=False))
    db.commit()
    assert mailer.select_template(db, "landing_hero") is None


# ----------------------------------------------------------- build_ctx
def test_build_ctx_resolves_offer_code_and_validity(db, admin):
    from app.core.settings_store import settings_store
    until = datetime(2026, 6, 17, 9, 0, tzinfo=timezone.utc)
    db.add(OfferCode(code="WELCOME20", discount_type="percent",
                     discount_value=20, valid_until=until, is_active=True,
                     created_by=admin.id))
    db.commit()
    settings_store.set("email.auto_offer_code", "welcome20",
                       db=db, updated_by=admin.id)
    settings_store.set("email.enroll_url", "https://x.test/pricing",
                       db=db, updated_by=admin.id)

    ctx = mailer.build_ctx(db, name="Alex", email="a@x.test")
    assert ctx["name"] == "Alex"
    assert ctx["offer_code"] == "welcome20"
    assert "2026" in ctx["offer_valid_until"]
    assert ctx["enroll_url"] == "https://x.test/pricing"


def test_build_ctx_defaults_when_unconfigured(db):
    # Settings cache (fakeredis + in-process) is shared across tests; clear
    # it so a prior test that set email.auto_offer_code can't leak in.
    from app.core import redis as redis_module
    from app.core.settings_store import _local
    redis_module.redis_client.flushall()
    _local.clear()
    ctx = mailer.build_ctx(db, name=None, email="a@x.test")
    assert ctx["name"] == "there"          # falls back when name missing
    assert ctx["offer_code"] == ""
    assert ctx["enroll_url"] == "/"         # fallback CTA target


# ----------------------------------------------------------- send_email
class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, context=None, timeout=None):
        self.host, self.port = host, port
        self.logged_in = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self, u, p): self.logged_in = (u, p)
    def starttls(self, context=None): pass
    def send_message(self, msg): self.sent = msg


@pytest.fixture
def _configured_smtp(db, admin):
    from app.core.settings_store import settings_store
    for k, v in {
        "email.smtp_host": "smtp.test",
        "email.smtp_port": 465,
        "email.smtp_use_ssl": True,
        "email.smtp_username": "contact@cpmaiexamprep.com",
        "email.smtp_password": "pw",
        "email.from_address": "contact@cpmaiexamprep.com",
        "email.from_name": "CPMAI Exam Prep",
    }.items():
        settings_store.set(k, v, db=db, updated_by=admin.id)


def test_send_email_success(monkeypatch, _configured_smtp):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
    ok = mailer.send_email("lead@x.test", "Subject",
                           "<p>Hello <strong>there</strong></p>")
    assert ok is True
    assert len(_FakeSMTP.instances) == 1
    msg = _FakeSMTP.instances[0].sent
    assert msg["To"] == "lead@x.test"
    assert msg["Subject"] == "Subject"
    assert "CPMAI Exam Prep" in msg["From"]


def test_send_email_unconfigured_returns_false(db):
    # No SMTP host set → fail-soft, returns False, never raises.
    assert mailer.send_email("lead@x.test", "S", "<p>x</p>") is False


def test_send_email_swallows_smtp_errors(monkeypatch, _configured_smtp):
    def _boom(*a, **k):
        raise smtplib.SMTPException("nope")
    monkeypatch.setattr(smtplib, "SMTP_SSL", _boom)
    assert mailer.send_email("lead@x.test", "S", "<p>x</p>") is False
