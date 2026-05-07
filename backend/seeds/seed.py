"""Seed runner. Idempotent — safe to re-run in any environment.

Bootstrap order:
  1. system_settings    — INSERT ... ON CONFLICT DO NOTHING
  2. topics             — INSERT ... ON CONFLICT DO NOTHING
  3. super-admin        — created if no super_admin exists
  4. questions          — inserted only if `questions` is empty
  5. exam_sets + links  — inserted only if `exam_sets` is empty;
                          links every sample question to every sample set

Existing user data is never overwritten. The "if empty" rules for sample
content prevent test data from leaking into a populated database.

Usage:
    docker compose exec backend python seeds/seed.py

Reads BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD from environment.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

# Ensure /app is on the path when invoked as a script.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402

import app.models  # noqa: E402, F401  -- triggers SQLAlchemy registration
from app.models.exam_set import ExamSet, ExamSetQuestion  # noqa: E402
from app.models.faq import FaqItem  # noqa: E402
from app.models.question import Difficulty, Question, QuestionOption  # noqa: E402
from app.models.system_setting import SystemSetting  # noqa: E402
from app.models.topic import Topic  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402


HERE = pathlib.Path(__file__).parent


def _load(name: str) -> list[dict]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def seed_settings(db) -> int:
    rows = _load("default_settings.json")
    existing = {s.key for s in db.query(SystemSetting).all()}
    added = 0
    for r in rows:
        if r["key"] in existing:
            continue
        db.add(SystemSetting(key=r["key"], value=r["value"],
                             description=r.get("description")))
        added += 1
    db.commit()
    return added


def seed_topics(db) -> int:
    rows = _load("topics.json")
    existing = {t.code for t in db.query(Topic).all()}
    added = 0
    for r in rows:
        if r["code"] in existing:
            continue
        db.add(Topic(code=r["code"], name=r["name"], order=r["order"]))
        added += 1
    db.commit()
    return added


def seed_faqs(db) -> int:
    """Insert default FAQs only if the FAQ table is empty.

    Once an admin has authored even one FAQ via /admin/faqs, this seeder
    leaves the table alone — same "fresh-only" rule as questions/exam_sets.
    """
    if db.query(FaqItem).first():
        return 0
    rows = _load("faqs_default.json")
    for r in rows:
        db.add(FaqItem(
            question=r["question"], answer=r["answer"],
            display_order=r.get("display_order", 100), is_active=True,
        ))
    db.commit()
    return len(rows)


def seed_super_admin(db) -> str | None:
    """Create a super-admin if none exists. Returns the email if created."""
    if db.query(User).filter_by(role=UserRole.SUPER_ADMIN).first():
        return None
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    if not email or not password:
        print("  ! BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD not set — "
              "skipping super-admin creation")
        return None
    db.add(User(email=email, password_hash=hash_password(password),
                name="Admin", role=UserRole.SUPER_ADMIN, is_active=True))
    db.commit()
    return email


def seed_sample_questions(db) -> list[int]:
    """Insert sample questions only if the table is empty. Returns IDs."""
    if db.query(Question).first():
        return [q.id for q in db.query(Question).all()]
    topics_by_code = {t.code: t for t in db.query(Topic).all()}
    rows = _load("questions_sample.json")
    ids: list[int] = []
    for r in rows:
        topic = topics_by_code.get(r["phase_code"])
        if topic is None:
            print(f"  ! topic {r['phase_code']} missing — skipping a question")
            continue
        q = Question(
            stem=r["stem"], topic_id=topic.id,
            domain=r.get("domain"), task=r.get("task"),
            enablers=r.get("enablers", []), remarks=r.get("remarks"),
            difficulty=Difficulty(r.get("difficulty", "medium")),
            explanation=r.get("explanation"), is_active=True,
        )
        for opt in r["options"]:
            q.options.append(QuestionOption(
                option_letter=opt["option_letter"], text=opt["text"],
                is_correct=opt.get("is_correct", False),
                reasoning=opt.get("reasoning"),
            ))
        db.add(q)
        db.flush()
        ids.append(q.id)
    db.commit()
    return ids


def seed_sample_exam_sets(db, question_ids: list[int]) -> int:
    """Insert sample sets only if the table is empty. Links every question to
    every set so candidates immediately see content to attempt."""
    if db.query(ExamSet).first():
        return 0
    rows = _load("exam_sets_sample.json")
    added = 0
    for r in rows:
        es = ExamSet(
            name=r["name"], slug=r["slug"], description=r.get("description"),
            difficulty=Difficulty(r.get("difficulty", "medium")),
            time_limit_minutes=r.get("time_limit_minutes", 90),
            passing_score=r.get("passing_score", 70),
            is_active=r.get("is_active", True),
            is_premium=r.get("is_premium", False),
            display_order=r.get("display_order", 100),
        )
        db.add(es)
        db.flush()
        for i, qid in enumerate(question_ids, start=1):
            db.add(ExamSetQuestion(
                exam_set_id=es.id, question_id=qid, position=i * 10,
            ))
        added += 1
    db.commit()
    return added


def main() -> None:
    print("Seeding (idempotent — safe to re-run)...")
    db = SessionLocal()
    try:
        n_settings = seed_settings(db)
        print(f"  system_settings: {n_settings} added "
              f"({db.query(SystemSetting).count()} total)")

        n_topics = seed_topics(db)
        print(f"  topics: {n_topics} added "
              f"({db.query(Topic).count()} total)")

        n_faqs = seed_faqs(db)
        print(f"  faqs: {n_faqs} added "
              f"({db.query(FaqItem).count()} total)")

        admin_email = seed_super_admin(db)
        if admin_email:
            print(f"  super-admin created: {admin_email}")
        else:
            print(f"  super-admin already present (skipped)")

        question_ids = seed_sample_questions(db)
        print(f"  questions: {db.query(Question).count()} total")

        n_sets = seed_sample_exam_sets(db, question_ids)
        print(f"  exam_sets: {n_sets} added "
              f"({db.query(ExamSet).count()} total, "
              f"{db.query(ExamSetQuestion).count()} links)")
    finally:
        db.close()
    print("Done.")


if __name__ == "__main__":
    main()
