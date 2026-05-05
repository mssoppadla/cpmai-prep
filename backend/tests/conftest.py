"""Shared pytest fixtures.

Uses an in-memory SQLite DB (per-test) for speed and a fakeredis instance
so tests don't need an actual Redis. The app's Razorpay integration is
patched out via fixtures that inject a fake provider into PaymentRegistry.
"""
import os
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Ensure required env vars BEFORE importing app modules
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-do-not-use-in-prod")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

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
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def fk_pragma(conn, _):
        cur = conn.cursor(); cur.execute("PRAGMA foreign_keys=ON"); cur.close()

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db(db_engine, monkeypatch):
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    from app.core import database as db_module
    monkeypatch.setattr(db_module, "SessionLocal", Session)
    monkeypatch.setattr(db_module, "engine", db_engine)
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
def client(db):
    """FastAPI TestClient. Imports app lazily so monkey-patches apply."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def auth_header(client, email: str, password: str = "password123") -> dict:
    r = client.post("/api/v1/auth/login",
                    json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access']}"}
