"""Shared pytest fixtures.

Uses an in-memory SQLite DB (per-test) for speed and a fakeredis instance
so tests don't need an actual Redis. The app's Razorpay integration is
patched out via fixtures that inject a fake provider into PaymentRegistry.

Wiring rules (these took a long debug session — don't unwind without
reading why):

  • StaticPool on the SQLite engine — `:memory:` is otherwise per-
    connection, so the test session and the request session would see
    different empty databases.
  • `client` fixture uses `app.dependency_overrides[get_db]` — NOT
    monkeypatching `SessionLocal`. Request handlers import SessionLocal
    into their own namespace at module load, so patching db_module's
    attribute doesn't reach them. Dependency override is the canonical
    FastAPI test pattern.
  • slowapi limiter is disabled for the duration of every test —
    its storage_uri points at the real Redis (or fakeredis), and
    counters accumulate across tests, so within seconds the 5/min
    auth-login limit fires and breaks unrelated tests.
"""
import os
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure required env vars BEFORE importing app modules
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-do-not-use-in-prod")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
# Starlette's TestClient sends Host: testserver. Force-include it in
# ALLOWED_HOSTS so TrustedHost middleware doesn't 400 every test request.
# We override (not setdefault) because CI may set a stricter value via the
# workflow env block — tests still need testserver regardless.
os.environ["ALLOWED_HOSTS"] = '["localhost","127.0.0.1","testserver"]'

# SQLite stores DateTime(timezone=True) as ISO text without TZ suffix when
# the value comes from `server_default=func.now()` (CURRENT_TIMESTAMP). On
# load that becomes a tz-NAIVE datetime — which can't be compared against
# `datetime.now(timezone.utc)` (TypeError). Postgres in prod doesn't have
# this issue. Patch SQLAlchemy's DateTime so loaded values from any column
# come back as tz-aware UTC, matching prod behavior.
from datetime import datetime as _datetime, timezone as _timezone
from sqlalchemy import DateTime as _SADateTime
_orig_dt_result_processor = _SADateTime.result_processor
def _aware_utc_result_processor(self, dialect, coltype):
    base = _orig_dt_result_processor(self, dialect, coltype)
    def proc(value):
        v = base(value) if base is not None else value
        if isinstance(v, _datetime) and v.tzinfo is None:
            v = v.replace(tzinfo=_timezone.utc)
        return v
    return proc
_SADateTime.result_processor = _aware_utc_result_processor

import fakeredis
from app.core import redis as redis_module
redis_module.redis_client = fakeredis.FakeRedis()

from app.core.database import Base
from app.core.security import hash_password
from app.models import (                                             # noqa
    User, UserRole, Topic, Question, QuestionOption, Difficulty,
    ExamSet, ExamSetQuestion, ExamSession, ExamAttemptAnswer,
    Subscription, Payment, WebhookEvent, Lead, LeadSource,
    AuditLog, JourneyEvent, SystemSetting, LLMProviderConfig,
    AssistantLog, PaymentProviderConfig,
)


@pytest.fixture
def db_engine():
    # StaticPool keeps the SAME connection across all callers, so the
    # in-memory database the test fixture writes to is the same one the
    # request handlers read from.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def fk_pragma(conn, _):
        cur = conn.cursor(); cur.execute("PRAGMA foreign_keys=ON"); cur.close()

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db(db_engine):
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    s = Session()
    try:
        # Seed the 6 CPMAI topics — many tests rely on these.
        topics = [
            ("BU", "Business Understanding", 1),
            ("DU", "Data Understanding", 2),
            ("DP", "Data Preparation", 3),
            ("MD", "Modeling", 4),
            ("EV", "Model Evaluation", 5),
            ("DE", "Model Operationalization", 6),
        ]
        for code, name, order in topics:
            s.add(Topic(code=code, name=name, order=order))
        s.commit()
        yield s
    finally:
        s.close()


@pytest.fixture
def user(db):
    u = User(email="alice@example.com",
             password_hash=hash_password("password123"),
             name="Alice", role=UserRole.USER)
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def admin(db):
    u = User(email="admin@example.com",
             password_hash=hash_password("password123"),
             name="Admin", role=UserRole.ADMIN)
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def super_admin(db):
    u = User(email="super@example.com",
             password_hash=hash_password("password123"),
             name="Super", role=UserRole.SUPER_ADMIN)
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def sample_question(db):
    """Standard 4-option question with one correct + per-option reasoning."""
    du = db.query(Topic).filter_by(code="DU").first()
    q = Question(
        stem="Which CPMAI phase assesses data quality?",
        topic_id=du.id,
        domain="Data Understanding > Data Quality Assessment",
        task="Identify and document data gaps",
        enablers=["Data profiling", "Quality metrics"],
        remarks="Easy phase recall.",
        difficulty=Difficulty.EASY,
        explanation="Phase 2 (Data Understanding) is where data is profiled and assessed.",
        is_active=True,
    )
    q.options = [
        QuestionOption(option_letter="A", text="Phase 1 — Business Understanding",
                       is_correct=False,
                       reasoning="Phase 1 defines the business goal, not data quality."),
        QuestionOption(option_letter="B", text="Phase 2 — Data Understanding",
                       is_correct=True,
                       reasoning="Correct — Phase 2 is dedicated to data assessment."),
        QuestionOption(option_letter="C", text="Phase 4 — Modeling",
                       is_correct=False,
                       reasoning="Modeling consumes prepared data; quality is assessed earlier."),
        QuestionOption(option_letter="D", text="Phase 6 — Model Operationalization",
                       is_correct=False,
                       reasoning="Operationalization is for deployed models, not raw data."),
    ]
    db.add(q); db.commit(); db.refresh(q)
    return q


@pytest.fixture
def sample_exam_set(db, sample_question, admin):
    es = ExamSet(name="Test Set", slug="test-set",
                 description="Tests", time_limit_minutes=30,
                 passing_score=70, is_active=True, created_by=admin.id)
    db.add(es); db.flush()
    db.add(ExamSetQuestion(exam_set_id=es.id, question_id=sample_question.id,
                            position=10, added_by=admin.id))
    db.commit(); db.refresh(es)
    return es


@pytest.fixture
def client(db_engine, db, monkeypatch):
    """FastAPI TestClient bound to the test SQLite engine.

    Three things are required for request handlers — and the supporting
    services they call — to see the same DB rows the fixtures wrote:

    1. The TestClient's request must use a session bound to db_engine.
       We accomplish this by registering a dependency override on get_db
       — request handlers depend on get_db, and FastAPI substitutes our
       override at injection time.
    2. Modules that bypass get_db and call `SessionLocal()` directly (the
       settings_store, llm_registry, payment_registry — non-request-bound
       background paths) need their SessionLocal *attribute* swapped for
       a test-engine-bound sessionmaker. monkeypatch on each module's
       attribute reaches the imported name they actually use.
    3. The connection pool must be StaticPool (configured on db_engine)
       so multiple sessions to `sqlite:///:memory:` see the same database
       instead of each spawning an empty in-memory DB.

    Also disables the slowapi rate limiter so tests can do many requests
    in quick succession without 429ing each other, and forces the chat
    cooldown to 0 so quota tests can fire 5 requests in a tight loop.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.deps import get_db
    from app.core.limiter import limiter
    from app.core.settings_store import settings_store, SettingsStore

    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    def override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db

    # Patch SessionLocal in every module that imported it at module load.
    # `from app.core.database import SessionLocal` binds SessionLocal as a
    # NAME in each importing module — patching db_module's attribute
    # doesn't reach those name bindings.
    for mod_path in (
        "app.core.settings_store",
        "app.services.assistant.llm_registry",
        "app.services.payment_registry",
    ):
        monkeypatch.setattr(f"{mod_path}.SessionLocal", Session, raising=False)

    # Disable rate limiter for test runs (state would accumulate in real
    # Redis in CI, breaking unrelated tests).
    was_enabled = limiter.enabled
    limiter.enabled = False

    # Force chat cooldown to 0 in tests so quota tests can fire requests
    # in a tight loop. Patch the get method on the SettingsStore class so
    # it short-circuits this one key. All other settings still resolve
    # normally through Redis/DB.
    orig_get = SettingsStore.get
    def _test_get(self, key, default=None):
        if key == "chat.cooldown_seconds":
            return 0
        return orig_get(self, key, default)
    monkeypatch.setattr(SettingsStore, "get", _test_get)

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        limiter.enabled = was_enabled


def auth_header(client, email: str, password: str = "password123") -> dict:
    r = client.post("/api/v1/auth/login",
                    json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access']}"}
