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
from app.core.security import hash_password, verify_password  # noqa: E402

import app.models  # noqa: E402, F401  -- triggers SQLAlchemy registration
from app.models.email_template import EmailTemplate  # noqa: E402
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
    """Insert default settings for any key that isn't already in the
    table. Honors the ``is_secret`` flag in the seed file — used so that
    a fresh install of a secret key correctly opts into masked
    /admin/settings responses, even before the admin has ever PATCH'd
    a value. (PATCH later also sets the flag — see admin/settings.py —
    so this just makes the first-deploy state correct.)
    """
    rows = _load("default_settings.json")
    existing = {s.key for s in db.query(SystemSetting).all()}
    added = 0
    for r in rows:
        if r["key"] in existing:
            continue
        db.add(SystemSetting(
            key=r["key"], value=r["value"],
            description=r.get("description"),
            is_secret=bool(r.get("is_secret", False)),
        ))
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


_DEFAULT_EMAIL_TEMPLATE_BODY = (
    '<div style="font-family: Arial, sans-serif; color: #1e293b; '
    'line-height: 1.6;">\n'
    "  <p>Hi {{name}},</p>\n"
    "  <p>Thanks for signing up for the free CPMAI mock exam! 🎉</p>\n"
    "  <p>As a welcome, here's an exclusive offer to enroll in the full "
    "<strong>course + exam bundle</strong>:</p>\n"
    '  <p style="font-size: 22px; font-weight: bold; color: #4f46e5; '
    'background: #eef2ff; padding: 12px 16px; border-radius: 8px; '
    'display: inline-block;">{{offer_code}}</p>\n'
    '  <p style="color: #b91c1c;"><strong>Hurry — this code is active for '
    "24 hours (until {{offer_valid_until}}).</strong></p>\n"
    '  <p><a href="{{enroll_url}}" style="background: #4f46e5; color: #fff; '
    'padding: 12px 20px; border-radius: 8px; text-decoration: none; '
    'font-weight: bold;">Enroll now &rarr;</a></p>\n'
    "  <p>See you inside,<br/>The {{brand_name}} team</p>\n"
    "</div>"
)


def seed_email_templates(db) -> int:
    """Insert a default lead → auto-offer email template only if the
    table is empty. Fresh-only rule (same as FAQs): once an admin has
    authored a template via /admin/email-templates this seeder no-ops.

    The default row (source = NULL) is the fallback used when no
    source-specific active template matches, so the automation always
    has something to send once SMTP + the offer code are configured.
    """
    if db.query(EmailTemplate).first():
        return 0
    db.add(EmailTemplate(
        source=None,
        subject="Your CPMAI welcome offer (24 hours only) 🎁",
        html_body=_DEFAULT_EMAIL_TEMPLATE_BODY,
        is_active=True,
    ))
    db.commit()
    return 1


def seed_email_automations(db) -> int:
    """Insert the four shipped lifecycle mail types only if the table is
    empty (fresh-only rule, same as email_templates). Every row ships
    ``is_active=False`` — nothing sends until the admin reviews the
    copy, configures SMTP, and flips BOTH the per-type toggle and the
    ``email.lifecycle_enabled`` master switch.

    Contract: docs/contracts/email-automation.md §0.
    """
    from app.models.email_automation import EmailAutomation
    if db.query(EmailAutomation).first():
        return 0
    rows = [
        EmailAutomation(
            name="Welcome — signup without payment",
            trigger_key="user.signup",
            conditions=[{"type": "has_active_subscription", "value": False}],
            delay_minutes=20,
            send_policy="once_per_user",
            subject="Welcome to {{brand_name}}, {{name}} — your free study kit",
            html_body=(
                "<p>Hi {{name}},</p>"
                "<p>Welcome to {{brand_name}}! Your account is ready.</p>"
                "<p>To help you get started we've attached free preparation "
                "material — and when you're ready for full mock exams and "
                "the complete course, use code <b>{{offer_code}}</b> "
                "(valid until {{offer_valid_until}}).</p>"
                "<p><a href=\"{{enroll_url}}\">Explore the full program</a></p>"
                "<p>— The {{brand_name}} team</p>"
            ),
        ),
        EmailAutomation(
            name="Payment received",
            trigger_key="payment.success",
            conditions=[],
            delay_minutes=0,
            send_policy="every_event",
            subject="Payment received — welcome aboard, {{name}}!",
            html_body=(
                "<p>Hi {{name}},</p>"
                "<p>We've received your payment of {{currency}} {{amount}} "
                "for <b>{{plan_name}}</b>. Your access is active until "
                "{{expires_at}}.</p>"
                "<p><a href=\"{{enroll_url}}\">Start learning now</a></p>"
                "<p>— The {{brand_name}} team</p>"
            ),
        ),
        EmailAutomation(
            name="Exam follow-up (2 days)",
            trigger_key="exam.submitted",
            conditions=[],
            delay_minutes=2880,
            send_policy="replace_pending",
            subject="{{name}}, how did {{exam_title}} feel? Next steps inside",
            html_body=(
                "<p>Hi {{name}},</p>"
                "<p>Two days ago you {{passed}} <b>{{exam_title}}</b> with a "
                "score of {{score}}%. Consistent practice is what turns a "
                "score into a certification.</p>"
                "<p><a href=\"{{enroll_url}}\">Take your next mock exam</a></p>"
                "<p>— The {{brand_name}} team</p>"
            ),
        ),
        EmailAutomation(
            name="Payment failed — need help?",
            trigger_key="payment.failed",
            conditions=[],
            delay_minutes=30,
            send_policy="every_event",
            cooldown_days=1,
            subject="{{name}}, your payment didn't go through — can we help?",
            html_body=(
                "<p>Hi {{name}},</p>"
                "<p>Your payment for <b>{{plan_name}}</b> "
                "({{currency}} {{amount}}) didn't complete. This usually "
                "resolves by retrying or using another payment method.</p>"
                "<p><a href=\"{{enroll_url}}\">Try again</a> — or just reply "
                "to this email and we'll help you sort it out.</p>"
                "<p>— The {{brand_name}} team</p>"
            ),
        ),
    ]
    for r in rows:
        db.add(r)
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


def seed_smoke_admin(db) -> str | None:
    """Create or sync a SEPARATE super-admin used only by the smoke test.

    Why separate: the bootstrap admin's password gets rotated by operators
    via /admin/users (or psql) and the .env value goes stale. The smoke
    account stays in sync with SMOKE_ADMIN_PASSWORD in .env so rotating the
    real admin never breaks the deploy gate.

    Idempotent: if the user already exists with the right password, no-op;
    if the password in .env was rotated, the DB hash is updated to match;
    if the user doesn't exist, it's created.

    Returns a status string for logging, or None if env values aren't set.
    """
    email = os.environ.get("SMOKE_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("SMOKE_ADMIN_PASSWORD", "").strip()
    if not email or not password:
        return None
    user = db.query(User).filter(User.email == email).first()
    if user:
        # Sync the password if the env value diverged from the DB hash.
        if not verify_password(password, user.password_hash or ""):
            user.password_hash = hash_password(password)
            user.is_active = True
            user.role = UserRole.SUPER_ADMIN
            db.commit()
            return f"{email} (password synced)"
        return None
    db.add(User(email=email, password_hash=hash_password(password),
                name="Smoke Admin", role=UserRole.SUPER_ADMIN, is_active=True))
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

        n_email_tpl = seed_email_templates(db)
        print(f"  email_templates: {n_email_tpl} added "
              f"({db.query(EmailTemplate).count()} total)")

        from app.models.email_automation import EmailAutomation
        n_email_auto = seed_email_automations(db)
        print(f"  email_automations: {n_email_auto} added "
              f"({db.query(EmailAutomation).count()} total)")

        admin_email = seed_super_admin(db)
        if admin_email:
            print(f"  super-admin created: {admin_email}")
        else:
            print(f"  super-admin already present (skipped)")

        smoke = seed_smoke_admin(db)
        if smoke:
            print(f"  smoke admin: {smoke}")
        else:
            # Either env vars aren't set, or the user already exists with
            # the correct password. Both are normal on subsequent runs.
            pass

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
